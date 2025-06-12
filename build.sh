#!/bin/bash
set -e

echo "Starting build process..."

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Make sure prisma is installed and in PATH
echo "Installing and upgrading Prisma..."
pip install prisma==0.11.0 --upgrade

# Generate Prisma client with explicit path
echo "Generating Prisma client..."
python -m prisma generate

# Show Python and Prisma versions
echo "Python version:"
python --version

echo "Prisma version:"
python -c "from importlib.metadata import version; print(version('prisma'))"

# Output directory contents for debugging
echo "Build directory contents:"
ls -la

# Check for critical files
echo "Checking for critical files..."
if [ -d "./__pypackages__" ]; then
  echo "Prisma package directory exists:"
  ls -la ./__pypackages__
fi

if [ -d "./prisma" ]; then
  echo "Prisma directory exists:"
  ls -la ./prisma
fi

echo "Environment variables (masked):"
env | grep -v -E "SECRET|PASSWORD|KEY" | sort

echo "Build completed successfully!" 