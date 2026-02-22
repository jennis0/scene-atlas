# Goal
You are helping to build Scene Atlas - a tool to help users view and search a large quantity of battlemaps for tabletop RPGs.

The key features are:
- Search battlemaps by name, author, features, 'tags', and semantic description of the image via web UI in a clean, modern interface
- Upload battlesmaps via the web UI
- Support for 'variants' of a battlemap, in particular we group them into 'variant groups' as many battlemaps are created with lots of different version (E.g. snowy, fey,summer, etc.)

# Working Principles
- Ignore anything in ./ignore
- Store all architectural decisions, as well as detailed design notes, and any notes that should be left for future workers in markdown files in ./design. Keep these updated as you work
- Remember to focus on planning first before execution. 
- Build with software engineering best principles in mind, we're making a long term solution, not a quick prototype.
- When designing the frontend, use the frontend-design skill 
- When you don't know something, check the docs in ./design before looking at code - it will point you to the right place
- Be critical at all times, make sure you challenge my assumptions, especially when they're implicit. I give you permission to push back if my ideas are not good ones
- Where possible, write tests to monitor behaviour