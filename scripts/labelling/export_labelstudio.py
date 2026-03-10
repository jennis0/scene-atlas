"""Export labels.jsonl to Label Studio JSON format."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urljoin


def generate_labelstudio_xml() -> str:
    """Generate the Label Studio labeling interface XML configuration."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<View>
  <Image name="image" value="$image"/>

  <View style="box-shadow: 2px 2px 5px rgba(0,0,0,0.1); padding: 10px">
    <Text value="Type:" style="font-weight: bold;"/>
    <Choices name="type" toName="image">
      <Choice value="battlemap"/>
      <Choice value="scene"/>
      <Choice value="map"/>
      <Choice value="other"/>
    </Choices>
  </View>

  <View style="box-shadow: 2px 2px 5px rgba(0,0,0,0.1); padding: 10px">
    <Text value="Grid:" style="font-weight: bold;"/>
    <Choices name="grid" toName="image">
      <Choice value="square"/>
      <Choice value="hex"/>
      <Choice value="none"/>
    </Choices>
  </View>

  <View style="box-shadow: 2px 2px 5px rgba(0,0,0,0.1); padding: 10px">
    <Text value="Description (Standard):" style="font-weight: bold;"/>
    <TextArea name="description_standard" toName="image" rows="3" placeholder="Full sentence, comprehensive visual description"/>
  </View>

  <View style="box-shadow: 2px 2px 5px rgba(0,0,0,0.1); padding: 10px">
    <Text value="Description (Search):" style="font-weight: bold;"/>
    <TextArea name="description_search" toName="image" rows="2" placeholder="Comma-separated keywords and phrases"/>
  </View>

  <View style="box-shadow: 2px 2px 5px rgba(0,0,0,0.1); padding: 10px">
    <Text value="Description (Terse):" style="font-weight: bold;"/>
    <TextArea name="description_terse" toName="image" rows="1" placeholder="Single short noun phrase"/>
  </View>
</View>"""


def load_jsonl(path: Path) -> list[dict]:
    """Load JSONL file and return list of parsed objects."""
    items = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"Warning: Failed to parse line: {line}", file=sys.stderr)
    return items


def build_labelstudio_task(
    task_id: int,
    relpath: str,
    image_url: str,
    label: dict,
) -> dict:
    """Convert a label dict to a Label Studio task object.

    Args:
        task_id: Unique task identifier
        relpath: The relative path of the image
        image_url: Full URL to the image
        label: The label dictionary with type, grid, and three descriptions

    Returns:
        A task dict in Label Studio format
    """
    result = [
        {
            "from_name": "type",
            "to_name": "image",
            "type": "choices",
            "value": {"choices": [label.get("type", "other")]},
            "id": f"type_{task_id}",
        },
        {
            "from_name": "grid",
            "to_name": "image",
            "type": "choices",
            "value": {"choices": [label.get("grid", "none")]},
            "id": f"grid_{task_id}",
        },
        {
            "from_name": "description_standard",
            "to_name": "image",
            "type": "textarea",
            "value": {"text": [label.get("description_standard", "")]},
            "id": f"desc_std_{task_id}",
        },
        {
            "from_name": "description_search",
            "to_name": "image",
            "type": "textarea",
            "value": {"text": [label.get("description_search", "")]},
            "id": f"desc_search_{task_id}",
        },
        {
            "from_name": "description_terse",
            "to_name": "image",
            "type": "textarea",
            "value": {"text": [label.get("description_terse", "")]},
            "id": f"desc_terse_{task_id}",
        },
    ]

    return {
        "id": task_id,
        "data": {"image": image_url},
        "annotations": [
            {
                "id": f"annotation_{task_id}",
                "completed_by": 1,
                "result": result,
                "was_cancelled": False,
                "ground_truth": False,
                "lead_time": 0.0,
                "created_at": "",
                "updated_at": "",
            }
        ],
        "predictions": [],
        "file_upload": None,
    }


def export_labelstudio(
    input_jsonl: Path,
    output_json: Path,
    image_base_url: str = "file://",
) -> int:
    """Export labels.jsonl to Label Studio JSON format.

    Args:
        input_jsonl: Path to labels.jsonl
        output_json: Path to write tasks.json
        image_base_url: Base URL for images. Each image URL = base_url + relpath

    Returns:
        0 on success, 1 on error
    """
    if not input_jsonl.exists():
        print(f"Error: input file does not exist: {input_jsonl}", file=sys.stderr)
        return 1

    labels = load_jsonl(input_jsonl)
    if not labels:
        print(f"Warning: no labels found in {input_jsonl}", file=sys.stderr)

    # Build Label Studio tasks
    tasks = []
    for idx, label in enumerate(labels, start=1):
        relpath = label.get("relpath", "")
        image_url = urljoin(image_base_url, relpath)
        task = build_labelstudio_task(idx, relpath, image_url, label)
        tasks.append(task)

    # Write output
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")

    print(f"Exported {len(tasks)} tasks to {output_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export labels.jsonl to Label Studio JSON format."
    )
    parser.add_argument("--input", required=True, help="Input labels.jsonl file")
    parser.add_argument("--output", required=True, help="Output tasks.json file")
    parser.add_argument(
        "--image-base-url",
        default="file://",
        help="Base URL for images. Full URL = base_url + relpath (default: file://)",
    )
    parser.add_argument(
        "--labelstudio-xml",
        help="Output path for Label Studio labeling interface XML (optional)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Export JSON
    result = export_labelstudio(input_path, output_path, args.image_base_url)
    if result != 0:
        return result

    # Optionally export XML
    if args.labelstudio_xml:
        xml_path = Path(args.labelstudio_xml)
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(generate_labelstudio_xml() + "\n", encoding="utf-8")
        print(f"Wrote Label Studio interface XML to {xml_path}")

    print("\nTo use in Label Studio:")
    print("1. Create a new project in Label Studio")
    print("2. In the labeling interface, paste the XML from the output file")
    print(f"3. Import the tasks from {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
