# Reveal.js Theme Guide

## Built-in Themes

Reveal.js comes with many built-in themes. Here are the most popular ones:

### Dark Themes
- **black** - Black background, white text (default)
- **night** - Dark blue background (currently using)
- **moon** - Dark blue-grey background
- **blood** - Dark background with blood red accents
- **league** - Grey background with cyan/blue accents

### Light Themes
- **white** - White background, black text
- **beige** - Beige background, brown text
- **sky** - Light blue background
- **serif** - Cream background, brown serif text
- **simple** - White background, minimal styling

### Colorful Themes
- **solarized** - Solarized color scheme
- **dracula** - Dracula color scheme (purple/pink)

## How to Change Theme

### Method 1: Edit the Markdown Header

Open `ai-agents-devops-demo.md` and change the `theme:` line:

```yaml
---
title: "Intelligent DevOps with Claude AI Agents"
theme: dracula  # <-- Change this line
highlightTheme: monokai
css: reveal-theme.css
---
```

### Method 2: Try Without Custom CSS

To see the pure theme without our customizations, temporarily remove the `css:` line:

```yaml
---
title: "Intelligent DevOps with Claude AI Agents"
theme: dracula
highlightTheme: monokai
# css: reveal-theme.css  # <-- Comment this out
---
```

## Popular Theme Combinations

### 1. Professional Dark (Current)
```yaml
theme: night
highlightTheme: monokai
css: reveal-theme.css  # Our custom gradients
```

### 2. Modern Dracula
```yaml
theme: dracula
highlightTheme: dracula
css: reveal-theme.css
```

### 3. Clean Light
```yaml
theme: white
highlightTheme: github
css: reveal-theme.css
```

### 4. Solarized
```yaml
theme: solarized
highlightTheme: solarized-light
# No custom CSS for pure solarized look
```

### 5. Blood (Dramatic)
```yaml
theme: blood
highlightTheme: monokai
css: reveal-theme.css
```

## Code Highlight Themes

The `highlightTheme` controls code block styling:

- **monokai** - Dark, colorful (current)
- **github** - Light, clean
- **dracula** - Purple/pink
- **solarized-light** - Beige
- **solarized-dark** - Dark blue
- **zenburn** - Low contrast dark
- **tomorrow** - Light, pastel
- **vs** - Visual Studio style

## Custom CSS Behavior

Our `reveal-theme.css` adds:
- Gradient backgrounds
- Glassmorphism effects
- Hover animations
- Pulsing metrics
- Custom table styling

**With custom CSS:** Enhanced visuals, modern effects
**Without custom CSS:** Pure reveal.js theme

## Quick Test

Want to try different themes quickly? Edit the markdown file and the live server will auto-reload:

1. Keep `./serve-presentation.sh` running
2. Edit `ai-agents-devops-demo.md`
3. Change `theme:` and `highlightTheme:`
4. Save the file
5. Browser auto-refreshes!

## Recommendation

For your AI Agents presentation, I recommend:

**Option 1: Dark Modern (Current)**
```yaml
theme: night
highlightTheme: monokai
css: reveal-theme.css
```
✅ Professional, modern, high contrast

**Option 2: Dracula (Colorful)**
```yaml
theme: dracula
highlightTheme: dracula
css: reveal-theme.css
```
✅ Eye-catching, tech-focused, purple/pink accents

**Option 3: Pure Night (No Custom CSS)**
```yaml
theme: night
highlightTheme: monokai
# css: reveal-theme.css  # Commented out
```
✅ Clean, simple, no distractions
