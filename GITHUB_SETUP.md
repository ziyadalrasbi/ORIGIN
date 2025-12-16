# Setting Up ORIGIN on GitHub

This guide will help you initialize this repository and connect it to GitHub.

## Step 1: Initialize Git Repository

If you haven't already initialized git, run:

```bash
# From the project root directory
git init
```

## Step 2: Create GitHub Repository

1. Go to [GitHub](https://github.com) and sign in
2. Click the **"+"** icon in the top right → **"New repository"**
3. Repository name: `ORIGIN` (or your preferred name)
4. Description: `API-First Upload Governance Infrastructure`
5. Choose **Private** (recommended for proprietary code) or **Public**
6. **DO NOT** initialize with README, .gitignore, or license (we already have these)
7. Click **"Create repository"**

## Step 3: Connect Local Repository to GitHub

After creating the repository, GitHub will show you commands. Use these:

```bash
# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: ORIGIN API-First Upload Governance System"

# Add GitHub remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/ORIGIN.git

# Or if using SSH:
# git remote add origin git@github.com:YOUR_USERNAME/ORIGIN.git

# Push to GitHub
git branch -M main
git push -u origin main
```

## Step 4: Verify

1. Go to your GitHub repository page
2. You should see all your files
3. The README.md should display on the repository homepage

## Optional: Set Up GitHub Actions Secrets

If you want to use CI/CD, you may need to set up secrets:

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. Add any required secrets (API keys, database URLs, etc.) for CI/CD

## Optional: Add Repository Topics

On your GitHub repository page:
1. Click the gear icon next to "About"
2. Add topics like: `api`, `governance`, `fastapi`, `python`, `ml`, `upload-governance`

## Branch Protection (Recommended)

For production repositories:
1. Go to **Settings** → **Branches**
2. Add a branch protection rule for `main`
3. Require pull request reviews before merging

## Next Steps

- Add collaborators in **Settings** → **Collaborators**
- Set up branch protection rules
- Configure GitHub Actions workflows (already included in `.github/workflows/ci.yml`)
- Add repository description and website if applicable

