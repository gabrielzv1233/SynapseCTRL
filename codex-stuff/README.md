# About This Folder

Most of the contents in this folder are no longer required for normal SynapseCTRL use or development.

This folder originally served as a **handoff to Codex**, containing the tools, reverse-engineering notes, observed Synapse behavior, and debugging utilities needed to explain how SynapseCTRL was originally able to:

- discover Razer devices
- read Synapse software profiles
- determine the active profile
- switch profiles through Synapse
- inspect Synapse's Electron internals

From that point, Codex was responsible for turning the proof-of-concept into a more practical, maintainable, and developer-friendly project.

Essentially, most work after the initial implementation was completed through Codex, aside from changes I made manually.

## Why This Folder Is Still Here

I'm intentionally leaving this folder in the repository because it still contains useful reverse-engineering and diagnostic tooling.

It may be useful for:

- investigating future Synapse updates
- inspecting renderer/storage behavior
- debugging compatibility issues
- understanding how SynapseCTRL works internally
- reproducing the original reverse-engineering process
- rebuilding or reimplementing SynapseCTRL from scratch if necessary

For normal usage, this folder can mostly be ignored.

See the main project documentation for the supported SynapseCTRL interfaces and setup instructions.