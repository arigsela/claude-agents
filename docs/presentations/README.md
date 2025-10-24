# AI Agents DevOps Demo Presentation

This directory contains the presentation materials for demonstrating the K8s Monitor and OnCall agents.

## Files

- `ai-agents-devops-demo.md` - Main presentation content (reveal.js markdown with embedded CSS)
- `custom-theme.css` - Additional custom styling (optional)
- `generate-presentation.sh` - Script to build the HTML presentation
- `README.md` - This file

## Visual Features

The presentation includes modern visual enhancements:

### 🎨 Design Elements
- **Gradient backgrounds** - Smooth color transitions for section slides
- **Glassmorphism effects** - Frosted glass look for icon grids
- **Hover animations** - Interactive cards that lift and glow on hover
- **Pulsing metrics** - Animated attention-grabbing statistics
- **Gradient text** - Eye-catching titles and headers
- **Custom progress bar** - Blue-to-green gradient progress indicator

### ✨ Animations
- **Convex transitions** - Smooth 3D slide transitions
- **Zoom backgrounds** - Dynamic background changes
- **Fade-in content** - Elegant content appearance
- **Pulse animations** - Key metrics pulse to draw attention
- **Hover effects** - Cards scale and elevate on hover
- **Underline animations** - H2 headers get animated underlines

### 🎯 Color Scheme
- **Primary**: Blue gradient (#3498db → #2980b9)
- **Success**: Green gradient (#27ae60 → #2ecc71)
- **Danger**: Red gradient (#c0392b → #e74c3c)
- **Dark**: Navy gradients for tech sections
- **Accent**: Purple gradient for titles (#667eea → #764ba2)

## Quick Start

### Option 1: Using Marp (Recommended)

```bash
# Generate the presentation
./generate-presentation.sh

# Open in browser
open ai-agents-devops-demo.html
```

### Option 2: Using reveal-md

```bash
# Install reveal-md (if not already installed)
npm install -g reveal-md

# Run presentation in browser with live reload
reveal-md ai-agents-devops-demo.md --theme black

# Or generate static HTML
reveal-md ai-agents-devops-demo.md --theme black --static ai-agents-devops-demo
```

## Presentation Structure

**Duration:** 30-40 minutes total (25-30 min presentation + 5-10 min Q&A)

### Slide Breakdown

1. **Title Slide** (1 min)
2. **Problem Statement** (3 min) - Slides 2-4
   - Manual troubleshooting challenges
   - Real-world impact (15-20 min avg)
3. **Solution Overview** (3 min) - Slides 5-7
   - Dual agent architecture
   - Comparison table
4. **K8s Monitor Agent** (8 min) - Slides 8-13
   - Claude Agent SDK features
   - 6 specialized subagents
   - MCP integration
   - Safety hooks
5. **OnCall Agent** (6 min) - Slides 14-17
   - Anthropic API direct
   - Dual-mode operation
   - n8n orchestration
6. **Benefits** (4 min) - Slides 18-20
   - K8s Monitor benefits
   - OnCall Agent benefits
   - When to use each
7. **Demo** (You present!) - Slides 21-23
   - K8s Monitor demo
   - OnCall Agent demo
8. **Conclusion** (2 min) - Slides 24-26
   - Summary
   - Q&A

## Presentation Tips

### Navigation
- **Arrow keys** or **Space** - Next/previous slide
- **F** - Fullscreen mode
- **O** - Overview mode (see all slides)
- **Esc** - Exit overview/fullscreen
- **S** - Speaker notes (if available)

### During the Demo
- Have both agents running beforehand:
  - K8s Monitor: Check recent monitoring cycle logs
  - OnCall Agent: Have Slack open in another tab
- Prepare 2-3 demo scenarios:
  1. Show recent Jira ticket created by K8s Monitor
  2. Ask OnCall Agent a question in Slack
  3. Show the correlation/memory features

### Customization

To modify the presentation:

1. Edit `ai-agents-devops-demo.md`
2. Regenerate: `./generate-presentation.sh`
3. Refresh browser to see changes

To change styling:

1. Edit `custom-theme.css`
2. Regenerate presentation

## Slide Highlights

### Key Visuals
- **Slide 3**: Icon-based problem visualization (reduces text overload)
- **Slide 4**: Large metric display (15-20 min impact)
- **Slide 6**: Simple architecture flow diagram
- **Slides 9-13**: Icon grids for features (visual engagement)
- **Slide 20**: Decision matrix table (when to use each)

### Audience Engagement
- **Mixed audience** (technical + management)
- **Visual-heavy** (icons, emojis, minimal text)
- **Focus areas**: Time savings, noise reduction, capabilities
- **No metrics deep-dive** (capabilities-focused)

## Demo Preparation Checklist

### Before Presenting

- [ ] K8s Monitor daemon is running
- [ ] OnCall Agent API is running (`./run_api_server.sh`)
- [ ] n8n workflow is active
- [ ] Slack channel is accessible
- [ ] Recent Jira tickets from K8s Monitor are visible
- [ ] Screenshot the .claude/ directory structure (for slide 11)
- [ ] Screenshot n8n workflow (optional, for slide 17)
- [ ] Test Slack bot interaction before demo

### Demo Scenarios

**K8s Monitor Demo (5 min):**
1. Show recent monitoring cycle logs
2. Display Jira ticket with full context (logs, events, GitHub PRs)
3. Show Teams notification
4. (Optional) Show safety hook blocking a dangerous command

**OnCall Agent Demo (5 min):**
1. Ask simple question: "@oncall-bot check proteus pods"
2. Follow-up question demonstrating memory: "Show me logs for the first one"
3. Complex question: "@oncall-bot why is [service] having issues?"
4. Show RCA report with correlation

## Technical Requirements

### Software
- Node.js 18+ (for Marp or reveal-md)
- Modern browser (Chrome, Firefox, Safari, Edge)

### For Live Demo
- K8s cluster access (dev-eks)
- Slack workspace access
- n8n instance running
- Both agents deployed and operational

## Troubleshooting

### Presentation won't generate
```bash
# Reinstall Marp
npm install -g @marp-team/marp-cli

# Or use reveal-md as fallback
npm install -g reveal-md
reveal-md ai-agents-devops-demo.md --theme black
```

### Slides look broken
- Some markdown renderers handle HTML/CSS differently
- Try both Marp and reveal-md to see which works better
- Icons (emojis) should work in all modern browsers

### Demo issues
- **K8s Monitor not running**: Check logs in `/tmp/eks-monitoring-daemon.log`
- **OnCall Agent not responding**: Verify API is running on port 8000
- **Slack bot offline**: Check n8n workflow is active

## Post-Presentation

After the demo, consider:
1. Sharing the presentation file with attendees
2. Creating a recording/walkthrough video
3. Documenting common Q&A for future reference
4. Gathering feedback on both agents

## Questions?

For help with the presentation or agents:
- Repository: `claude-agents/`
- Documentation: `docs/CLAUDE.md`
- Slack: #devops-ai-agents
