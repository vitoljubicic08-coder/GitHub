# CLAUDE.md - AI Assistant Development Guide

This document provides comprehensive guidance for AI assistants (like Claude) working with this codebase. It covers project structure, conventions, workflows, and best practices to ensure consistent and effective collaboration.

## Table of Contents

1. [Project Overview](#project-overview)
2. [Repository Structure](#repository-structure)
3. [Development Workflow](#development-workflow)
4. [Coding Conventions](#coding-conventions)
5. [Testing Guidelines](#testing-guidelines)
6. [Git Workflow](#git-workflow)
7. [Common Tasks](#common-tasks)
8. [AI Assistant Best Practices](#ai-assistant-best-practices)
9. [Troubleshooting](#troubleshooting)

---

## Project Overview

### Project Type
*To be filled in as project develops*

**Current State**: Empty repository awaiting initial project setup.

### Tech Stack
*Document primary technologies, frameworks, and tools here as they are added*

Example structure:
- **Language**: (e.g., Python 3.11+, TypeScript, Rust, Go)
- **Framework**: (e.g., React, Django, FastAPI, Express)
- **Build Tools**: (e.g., Webpack, Vite, Cargo, Make)
- **Package Manager**: (e.g., npm, pip, cargo)
- **Testing**: (e.g., Jest, pytest, Cargo test)
- **CI/CD**: (e.g., GitHub Actions, GitLab CI)

### Project Purpose
*Describe the main goals and use cases of this project*

### Key Dependencies
*List critical dependencies and their purposes*

---

## Repository Structure

### Current Structure
```
GitHub/
├── .git/              # Git version control metadata
└── CLAUDE.md         # This file
```

### Planned Structure
*Document the intended directory structure as it develops*

Example:
```
project-root/
├── src/              # Source code
│   ├── components/   # Reusable components
│   ├── services/     # Business logic
│   └── utils/        # Helper functions
├── tests/            # Test files
├── docs/             # Documentation
├── config/           # Configuration files
├── scripts/          # Build and utility scripts
├── .github/          # GitHub Actions workflows
├── package.json      # Dependencies (if Node.js)
├── README.md         # Project documentation
└── CLAUDE.md        # This file
```

### Key Directories

*Document each major directory's purpose as they are created*

---

## Development Workflow

### Initial Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd GitHub
   ```

2. **Install dependencies**
   *Add commands as project tools are established*
   ```bash
   # Example for Node.js:
   npm install

   # Example for Python:
   pip install -r requirements.txt
   ```

3. **Configure environment**
   *Document environment variables and configuration files*
   ```bash
   cp .env.example .env
   # Edit .env with appropriate values
   ```

### Development Process

1. **Create a feature branch**
   ```bash
   git checkout -b claude/<descriptive-name>-<session-id>
   ```

2. **Make changes**
   - Write code following conventions
   - Add tests for new functionality
   - Update documentation as needed

3. **Test changes**
   *Add testing commands as they are established*
   ```bash
   # Run tests
   # Run linters
   # Build project
   ```

4. **Commit and push**
   ```bash
   git add .
   git commit -m "Descriptive commit message"
   git push -u origin <branch-name>
   ```

5. **Create Pull Request**
   - Provide clear description
   - Reference related issues
   - Ensure CI/CD passes

---

## Coding Conventions

### General Principles

1. **Consistency**: Follow existing patterns in the codebase
2. **Clarity**: Write self-documenting code with clear names
3. **Simplicity**: Avoid over-engineering solutions
4. **DRY**: Don't Repeat Yourself - extract common patterns
5. **KISS**: Keep It Simple, Stupid - prefer simple solutions

### Code Style

*Document language-specific conventions as they are established*

#### Naming Conventions
- **Variables**: camelCase or snake_case (specify per language)
- **Functions**: descriptive verb phrases
- **Classes**: PascalCase
- **Constants**: UPPER_SNAKE_CASE
- **Files**: match primary export or module name

#### File Organization
- One primary class/component per file
- Group related utilities together
- Keep files focused and under 300-400 lines when possible

#### Comments and Documentation
- **DO**: Document why, not what
- **DO**: Add JSDoc/docstrings for public APIs
- **DON'T**: State the obvious
- **DON'T**: Leave commented-out code

Example:
```javascript
// Good: Explains why
// Using exponential backoff to handle rate limiting
await retryWithBackoff(apiCall);

// Bad: States the obvious
// Call the API
await apiCall();
```

### Error Handling

- Always handle errors gracefully
- Provide meaningful error messages
- Log errors with sufficient context
- Don't swallow exceptions silently

---

## Testing Guidelines

### Test Structure
*Document testing approach as it develops*

- **Unit Tests**: Test individual functions/components
- **Integration Tests**: Test component interactions
- **E2E Tests**: Test complete user workflows

### Testing Conventions

1. **Naming**: Test files should end with `.test.*` or `.spec.*`
2. **Organization**: Mirror source directory structure in tests
3. **Coverage**: Aim for >80% coverage for critical paths
4. **Isolation**: Tests should be independent and idempotent

### Running Tests

*Add commands as testing framework is established*

```bash
# Run all tests
npm test

# Run specific test file
npm test path/to/test.test.js

# Run with coverage
npm test -- --coverage

# Watch mode for development
npm test -- --watch
```

---

## Git Workflow

### Branch Strategy

**Branch Naming Convention**:
- Feature branches: `claude/<feature-name>-<session-id>`
- Bug fixes: `fix/<issue-description>`
- Documentation: `docs/<topic>`
- Refactoring: `refactor/<component-name>`

**Important**: Claude-created branches MUST:
- Start with `claude/`
- End with matching session ID
- Otherwise, push will fail with 403 HTTP error

### Commit Message Format

Follow conventional commits for clarity:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code restructuring (no feature change)
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples**:
```
feat(auth): add JWT token validation

Implements token validation middleware to verify JWT signatures
and expiration dates before allowing access to protected routes.

Closes #123
```

```
fix(api): handle null response from external service

Added null check to prevent crashes when external API returns
unexpected null values.
```

### Git Best Practices

1. **Commit Frequently**: Small, logical commits are easier to review
2. **Write Clear Messages**: Future you will thank present you
3. **Keep Commits Atomic**: Each commit should be a single logical change
4. **Test Before Committing**: Ensure tests pass before committing
5. **Pull Before Push**: Stay in sync with remote changes

### Git Commands Reference

```bash
# Check current status
git status

# View changes
git diff
git diff --staged

# Stage changes
git add <file>
git add .

# Commit
git commit -m "message"

# Push (with retry on network errors)
git push -u origin <branch-name>

# Fetch updates
git fetch origin <branch-name>

# Pull updates
git pull origin <branch-name>

# View log
git log --oneline --graph --decorate

# Create and switch to new branch
git checkout -b <branch-name>

# Switch branches
git checkout <branch-name>
```

### Network Error Handling

For `git push` and `git fetch/pull`:
- Retry up to 4 times on network failures
- Use exponential backoff: 2s, 4s, 8s, 16s
- Only retry on network errors, not on auth/permission errors

---

## Common Tasks

### Adding a New Feature

1. Create feature branch: `git checkout -b claude/add-feature-name-<session-id>`
2. Implement feature with tests
3. Update documentation
4. Run full test suite
5. Commit with descriptive message
6. Push and create PR

### Fixing a Bug

1. Reproduce the bug
2. Write a failing test that demonstrates it
3. Fix the bug
4. Verify test passes
5. Check for similar bugs elsewhere
6. Commit and push

### Refactoring Code

1. Ensure tests exist for area being refactored
2. Make small, incremental changes
3. Run tests after each change
4. Keep commits focused and atomic
5. Update documentation if interfaces change

### Adding Dependencies

1. Evaluate if dependency is necessary
2. Check license compatibility
3. Verify maintenance status and security
4. Install via package manager
5. Document why it's needed
6. Commit lock file with changes

---

## AI Assistant Best Practices

### General Guidelines

1. **Read Before Writing**: Always read existing files before modifying them
2. **Consistency**: Match existing code style and patterns
3. **Ask When Uncertain**: Use clarifying questions rather than assumptions
4. **Test Changes**: Run tests and build before committing
5. **Document Changes**: Update relevant documentation
6. **Atomic Changes**: One logical change per commit
7. **Context Awareness**: Consider impact on rest of codebase

### Code Modification Rules

1. **NEVER** modify files without reading them first
2. **ALWAYS** preserve existing code style and formatting
3. **PREFER** editing existing files over creating new ones
4. **AVOID** over-engineering or adding unnecessary features
5. **DON'T** add features not explicitly requested
6. **DON'T** refactor code beyond what's necessary
7. **DON'T** add comments to code you didn't change

### File Operations

1. **Read files**: Use Read tool for specific files
2. **Search code**: Use Grep for content search
3. **Find files**: Use Glob for pattern matching
4. **Edit files**: Use Edit tool for precise changes
5. **Write files**: Only for new files that are absolutely necessary

### Security Considerations

1. **Validate Input**: Never trust external input
2. **Avoid Secrets**: Never commit API keys, passwords, or tokens
3. **Use Environment Variables**: For configuration and secrets
4. **Check Dependencies**: Watch for vulnerabilities
5. **Follow Best Practices**: Use secure coding patterns

### Common Pitfalls to Avoid

1. **Repainting**: Ensure changes don't break existing functionality
2. **Breaking Changes**: Consider backward compatibility
3. **Silent Failures**: Always handle and log errors
4. **Missing Tests**: Don't skip testing new code
5. **Incomplete Documentation**: Update docs with code changes
6. **Overly Complex Solutions**: Start simple, add complexity only if needed

### Effective Communication

1. **Be Clear**: Explain what you're doing and why
2. **Be Concise**: Avoid unnecessary verbosity
3. **Be Proactive**: Anticipate issues and ask questions
4. **Be Honest**: Say when you're uncertain
5. **Provide Context**: Link to files with line numbers (e.g., `file.js:123`)

### Task Management

When working on complex tasks:

1. **Create TODO List**: Break down into steps
2. **Track Progress**: Update status as you work
3. **One at a Time**: Only one task in-progress at once
4. **Mark Complete**: Immediately after finishing each task
5. **Handle Blockers**: Create new tasks for issues discovered

### Example Workflow

```markdown
User: Add user authentication to the API

Claude:
1. I'll help add user authentication. Let me create a todo list:
   - Research existing authentication patterns in codebase
   - Design authentication flow
   - Implement authentication middleware
   - Add authentication tests
   - Update API documentation

2. Let me start by exploring the existing codebase...
   [Uses Task/Explore agent or Read/Grep tools]

3. Based on the existing patterns, I'll implement JWT-based authentication...
   [Implements feature step by step]

4. Tests are passing. Let me commit these changes...
   [Commits with clear message]

5. Authentication has been successfully added. The implementation includes:
   - JWT token generation and validation
   - Authentication middleware for protected routes
   - Comprehensive tests with >85% coverage
   - Updated API documentation
```

---

## Troubleshooting

### Common Issues

#### Build Failures

**Problem**: Build fails with dependency errors
**Solution**:
1. Clear dependency cache
2. Delete `node_modules/` or equivalent
3. Reinstall dependencies
4. Check for version conflicts

#### Test Failures

**Problem**: Tests fail intermittently
**Solution**:
1. Check for race conditions
2. Ensure tests are isolated
3. Look for shared state between tests
4. Run tests individually to identify culprit

#### Git Issues

**Problem**: Push fails with 403 error
**Solution**:
- Ensure branch starts with `claude/`
- Verify branch ends with correct session ID
- Check git credentials are configured

**Problem**: Merge conflicts
**Solution**:
1. Pull latest changes: `git pull origin <branch>`
2. Resolve conflicts manually
3. Test after resolving
4. Commit resolved changes

#### Environment Issues

**Problem**: Code works locally but fails in CI/CD
**Solution**:
1. Check environment variables are set
2. Verify dependency versions match
3. Review CI/CD logs for specific errors
4. Test with same Node/Python version as CI

### Getting Help

When stuck:
1. Check existing documentation
2. Search codebase for similar patterns
3. Review git history for context
4. Ask clarifying questions
5. Propose multiple solutions when uncertain

### Debugging Tips

1. **Read Error Messages Carefully**: They usually tell you what's wrong
2. **Check Recent Changes**: What changed since it last worked?
3. **Isolate the Problem**: Binary search to narrow down the issue
4. **Use Logging**: Add strategic log statements
5. **Reproduce Consistently**: Can you make it fail reliably?
6. **Check Assumptions**: What are you assuming that might be wrong?

---

## Appendix

### Useful Resources

*Add project-specific resources as they become relevant*

- **Documentation**: Link to main docs
- **API Reference**: Link to API docs
- **Style Guide**: Link to detailed style guide
- **Contributing**: Link to CONTRIBUTING.md
- **Issue Tracker**: Link to issues/bugs
- **Communication**: Link to team chat/forum

### Glossary

*Define project-specific terms and acronyms*

Example:
- **SL/TP**: Stop Loss / Take Profit
- **JWT**: JSON Web Token
- **API**: Application Programming Interface
- **CI/CD**: Continuous Integration / Continuous Deployment
- **PR**: Pull Request

### Version History

Track major updates to this document:

- **2026-01-15**: Initial creation of CLAUDE.md with comprehensive template
  - Added all major sections
  - Documented git workflow and conventions
  - Included AI assistant best practices

### Document Maintenance

This document should be updated:
- When project structure changes significantly
- When new conventions are established
- When new tools or frameworks are added
- When common issues/patterns emerge
- At least quarterly for accuracy review

**Last Updated**: 2026-01-15
**Maintainers**: AI Assistants (Claude) + Project Team
**Review Schedule**: Quarterly or on major changes

---

## Quick Reference Card

### Essential Commands
```bash
# Development
git checkout -b claude/<feature>-<id>  # Create branch
git status                              # Check status
git add .                               # Stage changes
git commit -m "type: message"           # Commit
git push -u origin <branch>             # Push

# Testing (examples - adjust for your stack)
npm test                                # Run tests
npm run build                           # Build project
npm run lint                            # Lint code

# Debugging
git log --oneline -10                   # Recent commits
git diff                                # View changes
git blame <file>                        # See who changed what
```

### Decision Tree for Changes

```
Need to make changes?
├─ Have you read the existing code? → No? READ IT FIRST
├─ Is this adding a new feature?
│  ├─ Was it requested? → No? DON'T ADD IT
│  └─ Yes? → Implement with tests
├─ Is this fixing a bug?
│  ├─ Can you reproduce it? → No? Find reproduction first
│  └─ Yes? → Write failing test, fix, verify
├─ Is this refactoring?
│  ├─ Is it necessary? → No? DON'T DO IT
│  ├─ Are tests in place? → No? Add tests first
│  └─ Yes? → Refactor incrementally
└─ Ready to commit?
   ├─ Do tests pass? → No? Fix tests
   ├─ Is documentation updated? → No? Update docs
   └─ Yes? → Commit and push
```

### Code Quality Checklist

Before committing, verify:
- [ ] Code follows existing style and conventions
- [ ] Tests are written and passing
- [ ] Documentation is updated
- [ ] No debug code or commented-out code
- [ ] No hardcoded secrets or credentials
- [ ] Error handling is appropriate
- [ ] Changes are focused and atomic
- [ ] Commit message is clear and descriptive

---

## Conclusion

This CLAUDE.md file is a living document that should evolve with the project. As the codebase grows and patterns emerge, update this file to reflect the current state and best practices.

The goal is to enable AI assistants to work effectively and consistently with the codebase, making intelligent decisions that align with project goals and team conventions.

**Remember**: When in doubt, ask questions. It's better to clarify than to make assumptions that lead to rework.

Happy coding!