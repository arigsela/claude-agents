#!/usr/bin/env bash
# Skill management utility functions
# Part of the Claude Code Skills Marketplace

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Default paths
SKILLS_DIR="${SKILLS_DIR:-$HOME/.claude/skills}"
CATALOG_FILE="${SKILLS_DIR}/skills-catalog.json"
REGISTRIES_FILE="${SKILLS_DIR}/known-registries.json"

# Logging functions
log_info() { echo -e "${BLUE}ℹ${NC} $*"; }
log_success() { echo -e "${GREEN}✓${NC} $*"; }
log_warning() { echo -e "${YELLOW}⚠${NC} $*"; }
log_error() { echo -e "${RED}✗${NC} $*" >&2; }

# Check if jq is installed
check_jq() {
    if ! command -v jq &> /dev/null; then
        log_error "jq is required but not installed. Install it with: brew install jq"
        exit 1
    fi
}

# Check if yq is installed (for YAML parsing) - cached check
HAS_YQ=""
check_yq() {
    if [[ -z "$HAS_YQ" ]]; then
        if command -v yq &> /dev/null; then
            HAS_YQ="yes"
        else
            HAS_YQ="no"
        fi
    fi
    [[ "$HAS_YQ" == "yes" ]]
}

# Initialize skills directory and catalog
init_skills_dir() {
    if [[ ! -d "$SKILLS_DIR" ]]; then
        mkdir -p "$SKILLS_DIR"
        log_info "Created skills directory: $SKILLS_DIR"
    fi

    if [[ ! -f "$CATALOG_FILE" ]]; then
        cat > "$CATALOG_FILE" << 'EOF'
{
  "version": 1,
  "lastUpdated": "",
  "skills": {},
  "registries": {}
}
EOF
        log_info "Created skills catalog: $CATALOG_FILE"
    fi
}

# Parse SKILL.md frontmatter (YAML between --- markers)
parse_skill_metadata() {
    local skill_path="$1"
    local skill_md="$skill_path/SKILL.md"

    if [[ ! -f "$skill_md" ]]; then
        log_error "SKILL.md not found at: $skill_md"
        return 1
    fi

    # Extract frontmatter between --- markers
    local frontmatter
    frontmatter=$(awk '/^---$/{p=!p;next}p' "$skill_md" | head -50)

    if [[ -z "$frontmatter" ]]; then
        log_error "No frontmatter found in SKILL.md"
        return 1
    fi

    echo "$frontmatter"
}

# Get a specific field from SKILL.md frontmatter
# Supports nested fields like "author.name" via pure bash parsing
get_skill_field() {
    local skill_path="$1"
    local field="$2"
    local default="${3:-}"

    local frontmatter
    frontmatter=$(parse_skill_metadata "$skill_path" 2>/dev/null) || {
        echo "$default"
        return 0
    }

    local value=""
    if check_yq; then
        value=$(echo "$frontmatter" | yq -r ".$field // \"\"" 2>/dev/null)
    else
        # Pure bash fallback for YAML parsing
        if [[ "$field" == *"."* ]]; then
            # Handle nested fields like "author.name"
            local parent="${field%%.*}"
            local child="${field#*.}"
            local in_parent=false
            while IFS= read -r line; do
                if [[ "$line" =~ ^${parent}: ]]; then
                    in_parent=true
                elif [[ "$in_parent" == true ]]; then
                    if [[ "$line" =~ ^[[:space:]]+${child}:[[:space:]]*(.*) ]]; then
                        value="${BASH_REMATCH[1]}"
                        value="${value#\"}"  # Remove leading quote
                        value="${value%\"}"  # Remove trailing quote
                        break
                    elif [[ ! "$line" =~ ^[[:space:]] ]]; then
                        break  # Exit parent block
                    fi
                fi
            done <<< "$frontmatter"
        else
            # Simple top-level field
            value=$(echo "$frontmatter" | grep "^${field}:" | head -1 | sed "s/^${field}:[[:space:]]*//" | sed 's/^"\(.*\)"$/\1/')
        fi
    fi

    if [[ -z "$value" || "$value" == "null" ]]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# Get skill info as JSON
get_skill_json() {
    local skill_path="$1"
    local skill_md="$skill_path/SKILL.md"

    if [[ ! -f "$skill_md" ]]; then
        return 1
    fi

    local name description version author tags category repository license
    name=$(get_skill_field "$skill_path" "name" "unknown")
    description=$(get_skill_field "$skill_path" "description" "")
    version=$(get_skill_field "$skill_path" "version" "1.0.0")
    author=$(get_skill_field "$skill_path" "author.name" "unknown")
    tags=$(get_skill_field "$skill_path" "tags" "[]")
    category=$(get_skill_field "$skill_path" "category" "other")
    repository=$(get_skill_field "$skill_path" "repository" "")
    license=$(get_skill_field "$skill_path" "license" "")

    jq -n \
        --arg name "$name" \
        --arg description "$description" \
        --arg version "$version" \
        --arg author "$author" \
        --arg tags "$tags" \
        --arg category "$category" \
        --arg repository "$repository" \
        --arg license "$license" \
        --arg path "$skill_path" \
        '{
            name: $name,
            description: $description,
            version: $version,
            author: $author,
            tags: (try ($tags | fromjson) catch []),
            category: $category,
            repository: $repository,
            license: $license,
            path: $path
        }'
}

# List all installed skills
list_installed_skills() {
    local verbose="${1:-false}"

    if [[ ! -d "$SKILLS_DIR" ]]; then
        log_warning "Skills directory not found: $SKILLS_DIR"
        return 0
    fi

    local found=0
    for skill_dir in "$SKILLS_DIR"/*/; do
        if [[ -f "${skill_dir}SKILL.md" ]]; then
            found=1
            local name version category
            name=$(get_skill_field "${skill_dir%/}" "name" "$(basename "${skill_dir%/}")")
            version=$(get_skill_field "${skill_dir%/}" "version" "1.0.0")
            category=$(get_skill_field "${skill_dir%/}" "category" "other")

            if [[ "$verbose" == "true" ]]; then
                local description
                description=$(get_skill_field "${skill_dir%/}" "description" "")
                echo -e "${BOLD}$name${NC} v$version [$category]"
                if [[ -n "$description" ]]; then
                    echo "  $description"
                fi
                echo ""
            else
                printf "%-30s %-10s %s\n" "$name" "v$version" "[$category]"
            fi
        fi
    done

    if [[ $found -eq 0 ]]; then
        log_info "No skills installed"
    fi
}

# Search skills by query
search_skills() {
    local query="$1"
    local query_lower
    query_lower=$(echo "$query" | tr '[:upper:]' '[:lower:]')

    if [[ ! -d "$SKILLS_DIR" ]]; then
        log_warning "Skills directory not found: $SKILLS_DIR"
        return 0
    fi

    local found=0
    for skill_dir in "$SKILLS_DIR"/*/; do
        if [[ -f "${skill_dir}SKILL.md" ]]; then
            local name description tags
            name=$(get_skill_field "${skill_dir%/}" "name" "")
            description=$(get_skill_field "${skill_dir%/}" "description" "")
            tags=$(get_skill_field "${skill_dir%/}" "tags" "")

            local searchable
            searchable=$(echo "$name $description $tags" | tr '[:upper:]' '[:lower:]')

            if [[ "$searchable" == *"$query_lower"* ]]; then
                found=1
                local version category
                version=$(get_skill_field "${skill_dir%/}" "version" "1.0.0")
                category=$(get_skill_field "${skill_dir%/}" "category" "other")
                echo -e "${BOLD}$name${NC} v$version [$category]"
                echo "  $description"
                echo ""
            fi
        fi
    done

    if [[ $found -eq 0 ]]; then
        log_info "No skills found matching: $query"
    fi
}

# Show detailed skill info
show_skill_info() {
    local skill_name="$1"
    local skill_path="$SKILLS_DIR/$skill_name"

    if [[ ! -d "$skill_path" ]]; then
        log_error "Skill not found: $skill_name"
        return 1
    fi

    if [[ ! -f "$skill_path/SKILL.md" ]]; then
        log_error "SKILL.md not found for: $skill_name"
        return 1
    fi

    local name description version author tags category repository license
    name=$(get_skill_field "$skill_path" "name" "$skill_name")
    description=$(get_skill_field "$skill_path" "description" "")
    version=$(get_skill_field "$skill_path" "version" "1.0.0")
    author=$(get_skill_field "$skill_path" "author.name" "unknown")
    tags=$(get_skill_field "$skill_path" "tags" "[]")
    category=$(get_skill_field "$skill_path" "category" "other")
    repository=$(get_skill_field "$skill_path" "repository" "")
    license=$(get_skill_field "$skill_path" "license" "")

    echo -e "${BOLD}${CYAN}$name${NC} v$version"
    echo -e "${BOLD}Category:${NC} $category"
    echo -e "${BOLD}Author:${NC} $author"
    [[ -n "$license" ]] && echo -e "${BOLD}License:${NC} $license"
    [[ -n "$repository" ]] && echo -e "${BOLD}Repository:${NC} $repository"
    echo ""
    echo -e "${BOLD}Description:${NC}"
    echo "  $description"
    echo ""

    if [[ "$tags" != "[]" && "$tags" != "null" ]]; then
        echo -e "${BOLD}Tags:${NC} $tags"
        echo ""
    fi

    # Show requirements if any
    local tools skills
    tools=$(get_skill_field "$skill_path" "requires.tools" "")
    skills=$(get_skill_field "$skill_path" "requires.skills" "")

    if [[ -n "$tools" && "$tools" != "null" ]] || [[ -n "$skills" && "$skills" != "null" ]]; then
        echo -e "${BOLD}Requirements:${NC}"
        [[ -n "$tools" && "$tools" != "null" ]] && echo "  Tools: $tools"
        [[ -n "$skills" && "$skills" != "null" ]] && echo "  Skills: $skills"
        echo ""
    fi

    # Show file structure
    echo -e "${BOLD}Files:${NC}"
    find "$skill_path" -type f -name "*.md" -o -name "*.json" -o -name "*.py" -o -name "*.sh" 2>/dev/null | while read -r file; do
        echo "  ${file#$skill_path/}"
    done
}

# Validate SKILL.md file
validate_skill() {
    local skill_path="$1"
    local errors=0
    local warnings=0

    echo -e "${BOLD}Validating:${NC} $skill_path"
    echo ""

    local skill_md="$skill_path/SKILL.md"
    if [[ ! -f "$skill_md" ]]; then
        log_error "SKILL.md not found"
        return 1
    fi

    # Check required fields
    local name description
    name=$(get_skill_field "$skill_path" "name" "")
    description=$(get_skill_field "$skill_path" "description" "")

    if [[ -z "$name" ]]; then
        log_error "Required field 'name' is missing"
        ((errors++))
    else
        log_success "name: $name"
    fi

    if [[ -z "$description" ]]; then
        log_error "Required field 'description' is missing"
        ((errors++))
    else
        log_success "description: present (${#description} chars)"
    fi

    # Check optional but recommended fields
    local version author category
    version=$(get_skill_field "$skill_path" "version" "")
    author=$(get_skill_field "$skill_path" "author.name" "")
    category=$(get_skill_field "$skill_path" "category" "")

    if [[ -z "$version" ]]; then
        log_warning "Recommended field 'version' is missing (will default to 1.0.0)"
        ((warnings++))
    else
        # Validate semver format
        if [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            log_success "version: $version (valid semver)"
        else
            log_warning "version: $version (not strict semver format)"
            ((warnings++))
        fi
    fi

    if [[ -z "$author" ]]; then
        log_warning "Recommended field 'author.name' is missing"
        ((warnings++))
    else
        log_success "author: $author"
    fi

    if [[ -z "$category" ]]; then
        log_warning "Recommended field 'category' is missing"
        ((warnings++))
    else
        local valid_categories=("development" "productivity" "testing" "learning" "automation" "documentation" "other")
        if [[ " ${valid_categories[*]} " =~ " $category " ]]; then
            log_success "category: $category"
        else
            log_warning "category: $category (non-standard category)"
            ((warnings++))
        fi
    fi

    echo ""
    echo -e "${BOLD}Summary:${NC}"
    if [[ $errors -eq 0 && $warnings -eq 0 ]]; then
        log_success "Validation passed with no issues"
        return 0
    elif [[ $errors -eq 0 ]]; then
        log_warning "Validation passed with $warnings warning(s)"
        return 0
    else
        log_error "Validation failed with $errors error(s) and $warnings warning(s)"
        return 1
    fi
}

# Pack skill into .skill bundle (ZIP file)
pack_skill() {
    local skill_path="$1"
    local output_dir="${2:-.}"

    if [[ ! -d "$skill_path" ]]; then
        log_error "Skill directory not found: $skill_path"
        return 1
    fi

    local skill_name
    skill_name=$(get_skill_field "$skill_path" "name" "$(basename "$skill_path")")
    local version
    version=$(get_skill_field "$skill_path" "version" "1.0.0")

    local bundle_name="${skill_name}-${version}.skill"
    local bundle_path="${output_dir}/${bundle_name}"

    log_info "Packing skill: $skill_name v$version"

    # Create ZIP bundle
    (cd "$(dirname "$skill_path")" && zip -r "$bundle_path" "$(basename "$skill_path")" -x "*.git*" -x "*.DS_Store")

    if [[ -f "$bundle_path" ]]; then
        local size
        size=$(du -h "$bundle_path" | cut -f1)
        log_success "Created bundle: $bundle_path ($size)"
    else
        log_error "Failed to create bundle"
        return 1
    fi
}

# Add skill to catalog
add_to_catalog() {
    local skill_name="$1"
    local skill_path="$2"
    local source_type="${3:-local}"
    local source_ref="${4:-$skill_path}"

    check_jq

    local version
    version=$(get_skill_field "$skill_path" "version" "1.0.0")
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local tmp_file
    tmp_file=$(mktemp)

    jq --arg name "$skill_name" \
       --arg version "$version" \
       --arg path "$skill_path" \
       --arg installedAt "$timestamp" \
       --arg sourceType "$source_type" \
       --arg sourceRef "$source_ref" \
       '.skills[$name] = {
           name: $name,
           version: $version,
           path: $path,
           installedAt: $installedAt,
           source: {
               type: $sourceType,
               ref: $sourceRef
           }
       } | .lastUpdated = $installedAt' "$CATALOG_FILE" > "$tmp_file"

    mv "$tmp_file" "$CATALOG_FILE"
    log_success "Added $skill_name v$version to catalog"
}

# Remove skill from catalog
remove_from_catalog() {
    local skill_name="$1"

    check_jq

    local tmp_file
    tmp_file=$(mktemp)

    jq --arg name "$skill_name" 'del(.skills[$name])' "$CATALOG_FILE" > "$tmp_file"
    mv "$tmp_file" "$CATALOG_FILE"
    log_success "Removed $skill_name from catalog"
}

# Install skill from various sources
install_skill() {
    local source="$1"
    local version="${2:-}"

    # Determine source type
    if [[ -d "$source" ]]; then
        install_from_local "$source"
    elif [[ "$source" == *.skill ]]; then
        install_from_bundle "$source"
    elif [[ "$source" == github:* ]]; then
        install_from_github "${source#github:}" "$version"
    else
        # Assume it's a skill name from registry
        install_from_registry "$source" "$version"
    fi
}

# Install from local directory
install_from_local() {
    local source_path="$1"

    if [[ ! -f "$source_path/SKILL.md" ]]; then
        log_error "Not a valid skill: SKILL.md not found in $source_path"
        return 1
    fi

    local skill_name
    skill_name=$(get_skill_field "$source_path" "name" "$(basename "$source_path")")
    local target_path="$SKILLS_DIR/$skill_name"

    if [[ -d "$target_path" ]]; then
        log_warning "Skill already exists: $skill_name"
        read -p "Overwrite? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Installation cancelled"
            return 0
        fi
        rm -rf "$target_path"
    fi

    cp -r "$source_path" "$target_path"
    add_to_catalog "$skill_name" "$target_path" "local" "$source_path"

    log_success "Installed skill: $skill_name"
}

# Install from .skill bundle
install_from_bundle() {
    local bundle_path="$1"

    if [[ ! -f "$bundle_path" ]]; then
        log_error "Bundle not found: $bundle_path"
        return 1
    fi

    local tmp_dir
    tmp_dir=$(mktemp -d)

    log_info "Extracting bundle..."
    unzip -q "$bundle_path" -d "$tmp_dir"

    # Find the skill directory
    local skill_dir
    skill_dir=$(find "$tmp_dir" -name "SKILL.md" -exec dirname {} \; | head -1)

    if [[ -z "$skill_dir" ]]; then
        log_error "Invalid bundle: SKILL.md not found"
        rm -rf "$tmp_dir"
        return 1
    fi

    local skill_name
    skill_name=$(get_skill_field "$skill_dir" "name" "$(basename "$skill_dir")")
    local target_path="$SKILLS_DIR/$skill_name"

    if [[ -d "$target_path" ]]; then
        log_warning "Skill already exists: $skill_name"
        read -p "Overwrite? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Installation cancelled"
            rm -rf "$tmp_dir"
            return 0
        fi
        rm -rf "$target_path"
    fi

    cp -r "$skill_dir" "$target_path"
    add_to_catalog "$skill_name" "$target_path" "bundle" "$bundle_path"

    rm -rf "$tmp_dir"
    log_success "Installed skill: $skill_name"
}

# Install from GitHub
install_from_github() {
    local github_ref="$1"
    local version="${2:-}"

    # Parse github:user/repo/path format
    local user repo path branch
    IFS='/' read -r user repo path <<< "$github_ref"

    if [[ -z "$user" || -z "$repo" ]]; then
        log_error "Invalid GitHub reference: github:$github_ref"
        log_info "Expected format: github:user/repo[/path/to/skill][@branch]"
        return 1
    fi

    # Check for branch in version or use main
    branch="${version:-main}"

    local tmp_dir
    tmp_dir=$(mktemp -d)

    log_info "Cloning from GitHub: $user/$repo..."

    if ! git clone --depth 1 --branch "$branch" "https://github.com/$user/$repo.git" "$tmp_dir" 2>/dev/null; then
        log_error "Failed to clone repository"
        rm -rf "$tmp_dir"
        return 1
    fi

    local skill_dir="$tmp_dir"
    if [[ -n "$path" ]]; then
        skill_dir="$tmp_dir/$path"
    fi

    if [[ ! -f "$skill_dir/SKILL.md" ]]; then
        log_error "SKILL.md not found at: $skill_dir"
        rm -rf "$tmp_dir"
        return 1
    fi

    local skill_name
    skill_name=$(get_skill_field "$skill_dir" "name" "$(basename "$skill_dir")")
    local target_path="$SKILLS_DIR/$skill_name"

    if [[ -d "$target_path" ]]; then
        log_warning "Skill already exists: $skill_name"
        read -p "Overwrite? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Installation cancelled"
            rm -rf "$tmp_dir"
            return 0
        fi
        rm -rf "$target_path"
    fi

    cp -r "$skill_dir" "$target_path"
    rm -rf "$target_path/.git"
    add_to_catalog "$skill_name" "$target_path" "github" "github:$github_ref"

    rm -rf "$tmp_dir"
    log_success "Installed skill: $skill_name"
}

# Install from registry (placeholder)
install_from_registry() {
    local skill_name="$1"
    local version="${2:-}"

    log_error "Registry installation not yet implemented"
    log_info "Use 'github:user/repo/path' to install from GitHub directly"
    return 1
}

# Update skill
update_skill() {
    local skill_name="$1"
    local skill_path="$SKILLS_DIR/$skill_name"

    if [[ ! -d "$skill_path" ]]; then
        log_error "Skill not found: $skill_name"
        return 1
    fi

    check_jq

    # Get source info from catalog
    local source_type source_ref
    source_type=$(jq -r ".skills[\"$skill_name\"].source.type // \"local\"" "$CATALOG_FILE")
    source_ref=$(jq -r ".skills[\"$skill_name\"].source.ref // \"\"" "$CATALOG_FILE")

    case "$source_type" in
        github)
            log_info "Updating from GitHub..."
            rm -rf "$skill_path"
            install_from_github "${source_ref#github:}"
            ;;
        bundle)
            log_info "Cannot auto-update bundle installations"
            log_info "Re-install with: claude skill add $source_ref"
            ;;
        local)
            log_info "Local skills cannot be auto-updated"
            ;;
        *)
            log_error "Unknown source type: $source_type"
            return 1
            ;;
    esac
}

# Check for updates
check_updates() {
    log_info "Checking for updates..."

    check_jq

    if [[ ! -f "$CATALOG_FILE" ]]; then
        log_warning "No catalog found"
        return 0
    fi

    local skills
    skills=$(jq -r '.skills | keys[]' "$CATALOG_FILE")

    local updates_available=0
    for skill_name in $skills; do
        local source_type
        source_type=$(jq -r ".skills[\"$skill_name\"].source.type" "$CATALOG_FILE")

        if [[ "$source_type" == "github" ]]; then
            # Would need to check remote for updates
            log_info "$skill_name: checking GitHub..."
        fi
    done

    if [[ $updates_available -eq 0 ]]; then
        log_success "All skills are up to date"
    fi
}

# Remove skill
remove_skill() {
    local skill_name="$1"
    local skill_path="$SKILLS_DIR/$skill_name"

    if [[ ! -d "$skill_path" ]]; then
        log_error "Skill not found: $skill_name"
        return 1
    fi

    log_warning "This will remove: $skill_path"
    read -p "Continue? [y/N] " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Removal cancelled"
        return 0
    fi

    rm -rf "$skill_path"
    remove_from_catalog "$skill_name"

    log_success "Removed skill: $skill_name"
}
