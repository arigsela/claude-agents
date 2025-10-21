# Marp Setup and Usage Guide

This guide will help you install Marp and use it to present the AI-Powered Incident Triage presentation.

---

## What is Marp?

**Marp (Markdown Presentation Ecosystem)** is a tool that lets you create beautiful slide decks using Markdown. It's perfect for technical presentations because:

- ✅ **Version-controlled** - Track changes in Git
- ✅ **Developer-friendly** - Write slides in your favorite editor
- ✅ **Code-friendly** - Syntax highlighting built-in
- ✅ **Export flexibility** - PDF, HTML, PPTX
- ✅ **Customizable** - Themes, CSS, layouts

---

## Installation

### Option 1: Marp CLI (Command Line)

**For macOS:**
```bash
# Using npm (requires Node.js)
npm install -g @marp-team/marp-cli

# Using Homebrew
brew install marp-cli
```

**For Linux:**
```bash
# Using npm
npm install -g @marp-team/marp-cli

# Or download binary from GitHub
wget https://github.com/marp-team/marp-cli/releases/latest/download/marp-cli-linux.tar.gz
tar -xzf marp-cli-linux.tar.gz
sudo mv marp /usr/local/bin/
```

**For Windows:**
```bash
# Using npm
npm install -g @marp-team/marp-cli

# Or use Chocolatey
choco install marp-cli
```

**Verify installation:**
```bash
marp --version
# Should output: @marp-team/marp-cli vX.X.X
```

---

### Option 2: VS Code Extension (Recommended for Editing)

**For interactive editing with live preview:**

1. Open VS Code
2. Go to Extensions (Cmd+Shift+X or Ctrl+Shift+X)
3. Search for "Marp for VS Code"
4. Install the extension by Marp Team
5. Open any `.md` file with Marp frontmatter
6. Click the preview icon (top right) to see live preview

**Extension features:**
- Live preview as you type
- Export directly from VS Code
- Syntax highlighting
- IntelliSense for Marp directives

---

### Option 3: Docker (No Installation Required)

**Run Marp in Docker:**
```bash
# Convert a presentation
docker run --rm -v $PWD:/home/marp/app/ marpteam/marp-cli \
  docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.html

# Watch mode (auto-rebuild on changes)
docker run --rm -v $PWD:/home/marp/app/ -p 8080:8080 marpteam/marp-cli \
  docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -s
```

Then open http://localhost:8080 in your browser.

---

## Quick Start

### 1. View the Marp Presentation

```bash
# Navigate to the repository
cd claude-agents

# Open the Marp version in VS Code (if extension installed)
code docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md

# Or convert to HTML and open in browser
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.html
open presentation.html  # macOS
xdg-open presentation.html  # Linux
start presentation.html  # Windows
```

---

### 2. Present the Slides

**Option A: HTML presentation (recommended)**
```bash
# Generate HTML with presenter mode
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md \
  -o presentation.html \
  --html

# Open in browser
open presentation.html

# Presenter tips:
# - Press 'F' for fullscreen
# - Press 'P' for presenter mode (shows speaker notes)
# - Press '?' for keyboard shortcuts
# - Use arrow keys to navigate
```

**Option B: PDF for distribution**
```bash
# Generate PDF
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md \
  -o presentation.pdf \
  --allow-local-files

# This creates a PDF you can share
```

**Option C: PowerPoint for editing**
```bash
# Generate PPTX
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md \
  -o presentation.pptx

# Open in PowerPoint/Google Slides/Keynote for final tweaks
```

---

### 3. Watch Mode (Live Reload)

**For practicing your presentation:**
```bash
# Start server with live reload
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md \
  --server \
  --watch

# Output will show:
# [  INFO ] Server is listening at http://localhost:8080/
# [  INFO ] Watching /path/to/docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md

# Open http://localhost:8080 in your browser
# Any changes to the .md file will auto-reload
```

---

## Understanding Marp Syntax

### Basic Slide Structure

```markdown
---
marp: true
theme: default
paginate: true
---

# This is Slide 1
## Subtitle

Content goes here

---

# This is Slide 2

More content
```

**Key points:**
- Frontmatter (between `---`) configures the presentation
- `---` (three dashes) creates a new slide
- Standard Markdown formatting works

---

### Speaker Notes

Add notes that only you see in presenter mode:

```markdown
# My Slide Title

This is visible content on the slide.

<!--
Speaker notes go here!
- Remember to demo the EKS agent
- Mention the 97% time savings
- Ask audience about their pain points
-->
```

**To view speaker notes:**
1. Open HTML presentation
2. Press `P` to enter presenter mode
3. Notes appear in separate panel

---

### Animations and Builds

**Reveal content progressively:**

```markdown
# Features

* First bullet appears immediately
* <!-- .element: class="fragment" --> Second appears on click
* <!-- .element: class="fragment" --> Third appears on click
```

**Or use Marp's built-in support:**

```markdown
# Key Benefits

- Reduce MTTR by 97%
- <!-- .element: class="fragment fade-in" -->
- Auto-remediation with safety hooks
- <!-- .element: class="fragment fade-in" -->
- Pattern recognition at scale
- <!-- .element: class="fragment fade-in" -->
```

---

### Code Blocks with Syntax Highlighting

````markdown
# Live Demo

```bash
# Check monitoring daemon
docker compose logs -f eks-monitoring-daemon

# View latest report
cat /tmp/eks-monitoring-reports/latest.json
```

```python
# Agent client example
result = await client.query(
    "Check proteus-dev namespace health"
)
```
````

**Supported languages:** bash, python, javascript, yaml, json, etc.

---

### Two-Column Layouts

```markdown
---
<!-- _class: cols-2 -->

# Architecture Comparison

## Left Column
- Autonomous Agent
- Persistent memory
- Multi-agent coordination

## Right Column
- On-Demand API
- Stateless queries
- HTTP integration
```

---

### Custom Themes and Styling

**Use built-in themes:**
```markdown
---
marp: true
theme: gaia  # Options: default, gaia, uncover
---
```

**Or add custom CSS:**
```markdown
---
marp: true
style: |
  section {
    background-color: #1e1e1e;
    color: #ffffff;
  }
  h1 {
    color: #4ec9b0;
  }
  code {
    background: #2d2d2d;
  }
---
```

---

## Presentation Tips

### Before the Presentation

1. **Generate HTML version:**
   ```bash
   marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.html --html
   ```

2. **Test in presentation mode:**
   - Open `presentation.html` in browser
   - Press `P` to see speaker notes
   - Practice transitions

3. **Have backup formats:**
   ```bash
   # PDF backup (in case of browser issues)
   marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pdf

   # PPTX backup (in case you need to present from someone else's machine)
   marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pptx
   ```

4. **Embed demo recordings** (optional):
   - Record terminal sessions with `asciinema`
   - Embed in slides for reliable demos
   - See "Advanced Features" section below

---

### During the Presentation

**Keyboard shortcuts in HTML mode:**
- `→` / `←` - Next/Previous slide
- `F` - Fullscreen
- `P` - Presenter mode (speaker notes + timer)
- `C` - Clone window (for dual-screen presenting)
- `Home` / `End` - First/Last slide
- `G` - Go to specific slide number
- `?` - Show all shortcuts

**Presenter mode features:**
- Current slide + next slide preview
- Speaker notes
- Timer (elapsed time)
- Slide number

---

### After the Presentation

**Share the presentation:**

```bash
# Option 1: Share PDF
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pdf
# Email or upload to shared drive

# Option 2: Share HTML (interactive)
# Upload presentation.html to your web server or GitHub Pages

# Option 3: Share PPTX (editable)
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pptx
# Share via Google Drive, SharePoint, etc.
```

---

## Advanced Features

### Embedding Videos

```markdown
# Live Demo

<video controls width="800">
  <source src="demos/eks-agent-demo.mp4" type="video/mp4">
</video>
```

---

### Embedding Asciinema Recordings

**For terminal demos:**

1. **Record your terminal:**
   ```bash
   asciinema rec demos/eks-agent-demo.cast
   # Do your demo
   # Press Ctrl+D when done
   ```

2. **Embed in slide:**
   ```markdown
   # Demo: EKS Agent in Action

   <script src="https://asciinema.org/a/[id].js" id="asciicast-[id]" async></script>
   ```

3. **Or use self-hosted player:**
   ```html
   <asciinema-player src="demos/eks-agent-demo.cast"></asciinema-player>
   <script src="https://unpkg.com/asciinema-player@3.0.1/dist/bundle/asciinema-player.min.js"></script>
   <link rel="stylesheet" href="https://unpkg.com/asciinema-player@3.0.1/dist/bundle/asciinema-player.css">
   ```

---

### Background Images

```markdown
---
<!-- _backgroundImage: url('images/kubernetes-cluster.png') -->
<!-- _backgroundSize: cover -->
<!-- _backgroundOpacity: 0.3 -->

# AI-Powered Incident Triage

Reducing MTTR from hours to seconds
```

---

### Presenter View on Dual Monitors

**Setup for dual-monitor presenting:**

1. Open `presentation.html` in browser
2. Press `C` to clone window
3. Move cloned window to audience screen
4. Press `F` for fullscreen on audience screen
5. Keep main window on your screen
6. Press `P` on your screen for presenter mode

**Result:**
- Audience sees: Full slide
- You see: Current slide + next slide + speaker notes + timer

---

## Customizing the Presentation

### Edit Slide Content

```bash
# Open in your favorite editor
code docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md

# Or use VS Code with Marp extension for live preview
```

**Editing tips:**
- Each `---` creates a new slide
- Use `<!-- -->` for speaker notes
- Add images: `![alt text](path/to/image.png)`
- Embed code with triple backticks

---

### Modify Theme

**Create custom theme file:**

```css
/* File: themes/ai-incident-triage.css */

@import 'default';

section {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

h1 {
  color: #ffd700;
  border-bottom: 3px solid #ffd700;
}

code {
  background: rgba(0, 0, 0, 0.3);
  color: #4ec9b0;
}
```

**Use in presentation:**
```markdown
---
marp: true
theme: ai-incident-triage
---
```

---

### Add Custom Layouts

**Define layouts in frontmatter:**

```markdown
---
marp: true
style: |
  .columns {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }
---

<!-- _class: columns -->

# Two Column Slide

<div>

## Left Side
- Autonomous Agent
- Runs 24/7

</div>

<div>

## Right Side
- On-Demand API
- HTTP endpoints

</div>
```

---

## Troubleshooting

### Marp CLI Not Found

**Problem:** `marp: command not found`

**Solution:**
```bash
# Check if Node.js is installed
node --version

# If not, install Node.js first
# macOS:
brew install node

# Then install Marp CLI
npm install -g @marp-team/marp-cli
```

---

### Images Not Showing in PDF

**Problem:** Images appear in HTML but not PDF

**Solution:**
```bash
# Use --allow-local-files flag
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md \
  -o presentation.pdf \
  --allow-local-files
```

---

### Code Syntax Highlighting Not Working

**Problem:** Code blocks appear without syntax highlighting

**Solution:**
- Specify language after opening backticks:
  ````markdown
  ```python
  # Your code here
  ```
  ````
- Ensure using triple backticks (```)
- Check that language name is supported

---

### Presenter Mode Not Working

**Problem:** Pressing 'P' doesn't show presenter mode

**Solution:**
- Ensure you generated HTML with `--html` flag:
  ```bash
  marp presentation.marp.md -o presentation.html --html
  ```
- Make sure speaker notes use `<!-- -->` syntax
- Try in different browser (Chrome/Firefox recommended)

---

## File Structure

After setting up Marp, your repository will have:

```
claude-agents/
├── docs/
│   ├── AI_INCIDENT_TRIAGE_PRESENTATION.md      # Original markdown
│   ├── AI_INCIDENT_TRIAGE_PRESENTATION.marp.md # Marp-formatted version
│   ├── MARP_SETUP_GUIDE.md                     # This guide
│   └── images/                                  # Presentation images (optional)
├── themes/                                      # Custom Marp themes (optional)
│   └── ai-incident-triage.css
├── demos/                                       # Demo recordings (optional)
│   ├── eks-agent-demo.cast
│   └── oncall-api-demo.cast
└── presentation.html                            # Generated HTML (gitignored)
```

---

## Quick Reference Commands

```bash
# Install Marp CLI
npm install -g @marp-team/marp-cli

# Convert to HTML (recommended for presenting)
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.html --html

# Convert to PDF (for sharing)
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pdf --allow-local-files

# Convert to PowerPoint
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pptx

# Watch mode (live reload during editing)
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md --server --watch

# Custom theme
marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.html --theme themes/ai-incident-triage.css
```

---

## Next Steps

1. **Install Marp** (choose method above)
2. **Review the Marp-formatted presentation:**
   ```bash
   code docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md
   ```
3. **Generate HTML and practice:**
   ```bash
   marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.html --html
   open presentation.html
   # Press 'P' for presenter mode
   ```
4. **Customize as needed:**
   - Edit speaker notes
   - Adjust slide content
   - Add your own images/demos
5. **Create backups:**
   ```bash
   marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pdf
   marp docs/AI_INCIDENT_TRIAGE_PRESENTATION.marp.md -o presentation.pptx
   ```

---

## Additional Resources

**Official Marp Documentation:**
- Website: https://marp.app/
- CLI Docs: https://github.com/marp-team/marp-cli
- Syntax Guide: https://marpit.marp.app/markdown
- VS Code Extension: https://marketplace.visualstudio.com/items?itemName=marp-team.marp-vscode

**Examples and Themes:**
- Theme Gallery: https://github.com/marp-team/marp-core/tree/main/themes
- Example Presentations: https://github.com/yhatt/marp-cli-example

**Community:**
- GitHub Discussions: https://github.com/marp-team/marp/discussions
- Discord: https://discord.gg/marp

---

## Support

**Having issues?**
- Check the troubleshooting section above
- Review Marp documentation: https://marp.app/
- Ask in the team Slack channel: `#ai-incident-response`

**Want to contribute improvements?**
- Edit the `.marp.md` file
- Test changes with `marp --watch`
- Submit a PR with your improvements

---

**Happy Presenting! 🎉**
