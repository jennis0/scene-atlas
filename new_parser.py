import re
from pathlib import Path
from typing import List, Optional, Tuple, Set
from pydantic import BaseModel

class BattlemapEntry(BaseModel):
    author: str
    variant_group_name: str
    sub_variants: List[str] = []
    filename: str
    filepath: str
    tags: List[str] = []
    gridded: Optional[bool] = None
    dimensions: Optional[Tuple[int, int]] = None

class BattlemapParser:
    def __init__(self):
        self.camel_regex = re.compile(r'([a-z])([A-Z])|([a-zA-Z])([0-9])|([0-9])([a-zA-Z])')
        self.dim_regex = re.compile(r'[\(\[ ]?(\d{1,3})\s*[xX]\s*(\d{1,3})[\)\] ]?')
        self.by_author_regex = re.compile(r'[bB]y([A-Z][a-z]+|[A-Z]+|[a-z]+)')
        
        # Regex to find content inside () or []
        self.bracket_regex = re.compile(r'[\(\[](.*?)[\)\]]')
        
        self.generic_folders = {'singletons', 'variants', 'random', 'miscellaneous', 'assets'}
        self.grid_stop_words = {'gridded', 'grid', 'gridless', 'nogrid', 'no-grid'}
        self.junk_words = {'jpg', 'png', 'webp', 'vtt', '2mtt', 'community', 'no', 'the', 'and'}

    def _clean_string(self, text: str) -> str:
        """Helper to replace underscores with spaces and strip whitespace."""
        return text.replace('_', ' ').strip()

    def _get_token_set(self, text: str) -> Set[str]:
        """Normalizes a string into a set of lowercase words for comparison/filtering."""
        text = text.replace('_', ' ').replace('-', ' ')
        expanded = self.camel_regex.sub(lambda m: f"{m.group(1) or m.group(3) or m.group(5)} {m.group(2) or m.group(4) or m.group(6)}", text)
        return set(re.findall(r'[a-zA-Z0-9]+', expanded.lower()))

    def _extract_tags(self, stem: str, exclusions: Set[str]) -> List[str]:
        """Custom tag extractor that protects bracketed tokens."""
        # 1. Protect bracketed content
        protected_tokens = []
        def protect(m):
            content = m.group(1).replace('_', ' ').strip()
            protected_tokens.append(content)
            return " PROTECTED_TOKEN "
        
        working_stem = self.bracket_regex.sub(protect, stem)
        
        # 2. Process the remaining string for words
        working_stem = working_stem.replace('_', ' ').replace('-', ' ')
        working_stem = self.camel_regex.sub(lambda m: f"{m.group(1) or m.group(3) or m.group(5)} {m.group(2) or m.group(4) or m.group(6)}", working_stem)
        
        raw_words = re.findall(r'[a-zA-Z0-9]+', working_stem)
        
        # 3. Combine and Filter
        final_tags = []
        # Add protected tokens first (if not excluded)
        for token in protected_tokens:
            if token.lower() not in exclusions and not any(w in exclusions for w in token.lower().split()):
                final_tags.append(token)
        
        # Add individual words
        for word in raw_words:
            w_low = word.lower()
            if w_low not in exclusions and w_low not in self.junk_words and not w_low.isdigit() and len(w_low) > 1:
                if word not in ["PROTECTED", "TOKEN"]:
                    final_tags.append(word.capitalize())
        
        return final_tags

    def parse_line(self, raw_path: str) -> BattlemapEntry:
        clean_path = raw_path.strip()
        path_obj = Path(clean_path)
        parts = path_obj.parts
        stem = path_obj.stem
        
        # 1. Author & Grid (Same as V5)
        author = parts[0] if parts else "Unknown"
        author_match = self.by_author_regex.search(stem)
        if author_match: author = author_match.group(1)

        gridded = None
        lower_stem = stem.lower()
        if any(x in lower_stem for x in ['no grid', 'no-grid', 'gridless', 'nogrid']):
            gridded = False
        elif 'grid' in lower_stem:
            gridded = True

        # 2. Dimensions
        dimensions = None
        dim_match = self.dim_regex.search(stem)
        if dim_match:
            dimensions = (int(dim_match.group(1)), int(dim_match.group(2)))
            stem = stem.replace(dim_match.group(0), " ")

        # 3. Hierarchy & Group Name
        sub_variants_raw = []
        group_raw = "Unknown"
        if len(parts) >= 2:
            if parts[1].lower() in self.generic_folders and len(parts) > 2:
                group_raw = parts[2]
                sub_variants_raw = list(parts[3:-1])
            else:
                group_raw = parts[1]
                sub_variants_raw = list(parts[2:-1])
        
        if group_raw.lower() in self.generic_folders or group_raw == "Unknown":
            group_raw = re.split(r'[\-\(\[\,]', stem)[0].strip()

        # Clean variants and groups (Replace underscores with spaces)
        group_name = self._clean_string(group_raw)
        sub_variants = [self._clean_string(s) for s in sub_variants_raw]

        # 4. Tag Filtering Logic
        exclusions = {author.lower(), 'by'}
        exclusions.update(self.grid_stop_words)
        exclusions.update(self._get_token_set(group_name))
        for sub in sub_variants:
            exclusions.update(self._get_token_set(sub))
        if dimensions:
            exclusions.update([str(dimensions[0]), str(dimensions[1])])

        tags = self._extract_tags(stem, exclusions)

        return BattlemapEntry(
            author=author,
            variant_group_name=group_name,
            sub_variants=sub_variants,
            filename=path_obj.name,
            filepath=clean_path,
            tags=tags,
            gridded=gridded,
            dimensions=dimensions
        )

if __name__ == "__main__":
    parser = BattlemapParser()
    
    with open("filepaths.txt", 'r') as f:
        test_lines = f.readlines()
        
    # test_lines = [
    #     r".\2mtt\Ancient Tree Roots (23x16) Malicious, Night.jpg",
    #     r".\Czepeku\Ancient Dragon Skeleton\Variants\Blood Moon\Ancient_Dragon_Skeleton_Blood_Moon_Gridless_30x45.jpg",
    #     r".\2mtt\Abandoned House - Basement - Furnished - 8x6.png",
    #     r".\2mtt_community\2mttCommunity_2mtt100_AdventureGuildtavernbyBazz_InntavernadventureGuild2mt2ndFloorday.png"
    # ]

    for i in range(2000, 3000, 10):
        line = test_lines[i]
        data = parser.parse_line(line)
        print(line.strip())
        print("Path   :", data.filename)
        print("Author :", data.author)
        print("Variant:", data.variant_group_name)
        print("Sub    :",data.sub_variants)
        print("Tags   :",data.tags)
        print("Gridded:", data.gridded)
        print("Dim    :", data.dimensions)
        print("-" * 40)