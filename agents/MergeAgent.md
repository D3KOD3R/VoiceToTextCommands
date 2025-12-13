# MergeAgent — "Merge to Main" Workflow

The repo domain can be found in a file called RepoPointer.md use this for remote repo pushes. 

When the user says "merge to main", follow this complete workflow:
Always acknowledge this workflow before merge-related work; do not skip it.

## Pre-Merge Preparation
1. **Pull latest main** - Fetch and merge the latest changes from remote main.
2. **Validate branch naming** - Create a conventional commits conform branch using kebab-case:
   - `feat/feature-name` for new features
   - `fix/bug-name` for bug fixes
   - `docs/update-name` for documentation
   - `refactor/change-name` for code refactoring
   - `test/test-name` for test additions
   - `chore/task-name` for maintenance tasks

## Commit and Push
3. **Run pre-commit checks** - Execute tests and linters if applicable; report any failures.
4. **Commit changes** - Use detailed conventional commits messages:
   - Format: `type(scope): description`
   - Examples: `feat(auth): add user authentication`, `fix(dashboard): resolve memory leak`
   - Include body with details if changes are complex.
5. **Check for conflicts** - Ensure branch can merge cleanly with main.
6. **Push branch** - Push the branch to remote.

## Pull Request Creation
7. **Create Pull Request** - Generate PR to main with:
   - Descriptive title matching commit message format.
   - Body containing: changes summary, testing done, breaking changes (if any).
   - Link related issues if applicable.

## Confirmation and Merge
8. **Wait for CI/CD** - Allow automated checks to complete; report status.
9. **Present summary** - Show user:
   - All commits to be merged.
   - Files changed.
   - CI/CD status.
   - Any warnings or conflicts.
10. **Request confirmation** - Ask: "Ready to merge to main? (yes/no)".
11. **Merge PR** - After confirmation, merge using squash or merge commit (ask user preference).
12. **Verify merge** - Confirm merge was successful.

## Cleanup
13. **Delete remote branch** - Remove the feature branch from remote.
14. **Update local main** - Pull the updated main branch locally.
15. **Confirm completion** - Report successful merge with commit SHA.

## Error Handling
- **If tests fail**: Report failures and ask whether to fix or abort.
- **If merge conflicts exist**: Report conflicts and ask user to resolve manually.
- **If PR creation fails**: Report error and suggest manual creation.
- **If CI/CD fails**: Report failures and ask whether to fix or abort.

## Readme
- ** If there are dependencies that need to be installed first link the url of the dependencies in the readme in the sequential order of installation. 
