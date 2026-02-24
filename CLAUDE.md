# Goal
You are helping to build Scene Atlas - a tool to help users view and search a large quantity of tabletop RPG scenes (battlemaps, vistas, portraits, encounter art) via a web UI.

The key features are:
- Search scenes by name, author, features, 'tags', and semantic description of the image via web UI in a clean, modern interface
- Upload scenes via the web UI, with per-image type selection (battlemap or scene)
- Support for 'groups' of related images, as many battlemaps are created with lots of different versions (e.g. snowy, fey, summer, etc.). Groups can contain both battlemaps and scenes
- Type-aware processing: battlemaps get grid detection; scenes skip grid detection

The tool has three deployment modes
1. Running as a local electron app. This is targeted at non-technical users who want to access it for themselves
2. Running as a web server behind a reverse proxy. This is targeted at power users who want access to their maps, wherever they are, and potentially to sharing them with a small number of users
3. Developers - who need to be able to run a fully local version with hot reload of both backend and frontend code.

# Working Principles
- Ignore anything in ./ignore
- Store all architectural decisions, as well as detailed design notes, and any notes that should be left for future workers in markdown files in ./design. Keep these updated as you work
- Remember to focus on planning first before execution. 
- Build with software engineering best principles in mind, we're making a long term solution, not a quick prototype.
- When designing the frontend, use the frontend-design skill 
- When you don't know something, check the docs in ./design before looking at code - it will point you to the right place
- Be critical at all times, make sure you challenge my assumptions, especially when they're implicit. I give you permission to push back if my ideas are not good ones
- Where possible, write tests to monitor behaviour, look to increase test coverage gradually over time.
- When a feature request is particularly large, create a separate branch to work on it
- Whenever a bug is found, if possible, write tests to prevent that class of bug from occuring again

# How to Manage the Code
- When starting a new feature, do so in a worktree then ask the user to merge it into the primary working branch once complete
- Delete the worktree when the user confirms they're happy with the completed feature
- If working on small bugfixes, do so in your current worktree if one is available, otehrwise ask the user whether they want you to work on the main branch
- At the end of each feature or bugfix, commit it with a useful but short message
