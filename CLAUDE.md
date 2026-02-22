# Goal
You are helping to build Scene Atlas - a tool to help users view and search a large quantity of tabletop RPG scenes (battlemaps, vistas, portraits, encounter art) via a web UI.

The key features are:
- Search scenes by name, author, features, 'tags', and semantic description of the image via web UI in a clean, modern interface
- Upload scenes via the web UI, with per-image type selection (battlemap or scene)
- Support for 'groups' of related images, as many battlemaps are created with lots of different versions (e.g. snowy, fey, summer, etc.). Groups can contain both battlemaps and scenes
- Type-aware processing: battlemaps get grid detection; scenes skip grid detection

# Working Principles
- Ignore anything in ./ignore
- Store all architectural decisions, as well as detailed design notes, and any notes that should be left for future workers in markdown files in ./design. Keep these updated as you work
- Remember to focus on planning first before execution. 
- Build with software engineering best principles in mind, we're making a long term solution, not a quick prototype.
- When designing the frontend, use the frontend-design skill 
- When you don't know something, check the docs in ./design before looking at code - it will point you to the right place
- Be critical at all times, make sure you challenge my assumptions, especially when they're implicit. I give you permission to push back if my ideas are not good ones
- Where possible, write tests to monitor behaviour