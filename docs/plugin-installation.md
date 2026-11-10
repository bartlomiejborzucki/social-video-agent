# Codex plugin installation

Codex discovers repository plugins through `.agents/plugins/marketplace.json`. The marketplace entry points to `plugins/social-video-agent`, whose `skills` entry is a symbolic link to the repository's `skills/` directory, so the one canonical implementation at `skills/social-video-agent` is what Codex loads.

On a Windows checkout git only creates that link with `core.symlinks=true` and Developer Mode (or an elevated shell); otherwise it becomes a text file and `social-video-agent doctor` reports that the skills path does not exist. Clone inside WSL2, which is the supported layout, or re-clone with `git clone -c core.symlinks=true`.

## Install from GitHub

```bash
codex plugin marketplace add bartlomiejborzucki/social-video-agent
codex plugin add social-video-agent@social-video-agent
```

Restart the ChatGPT desktop app or begin a new Codex thread after installation.

## Local development

From a WSL checkout:

```bash
codex plugin marketplace add "$PWD"
codex plugin add social-video-agent@social-video-agent
```

After local changes, remove and add the plugin again so Codex refreshes its cache:

```bash
codex plugin remove social-video-agent@social-video-agent
codex plugin add social-video-agent@social-video-agent
```

For a GitHub-installed marketplace, update its snapshot and reinstall:

```bash
codex plugin marketplace upgrade social-video-agent
codex plugin remove social-video-agent@social-video-agent
codex plugin add social-video-agent@social-video-agent
```

The plugin carries instructions only. FFmpeg, Python dependencies, models, and the CLI stay in the WSL project environment.
