#!/bin/bash
set -e

echo "Starting build process..."

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Make sure prisma is installed and in PATH
echo "Installing and upgrading Prisma..."
pip install prisma==0.11.0 --upgrade

# Print DATABASE_URL (masked) for debugging
echo "Checking DATABASE_URL..."
if [ -z "$DATABASE_URL" ]; then
  echo "WARNING: DATABASE_URL is not set!"
else
  echo "DATABASE_URL is set (value masked for security)"
fi

# Generate Prisma client with explicit path and force
echo "Generating Prisma client..."
python -m prisma generate --schema=./prisma/schema.prisma

# Verify Prisma client was generated
echo "Checking for Prisma client..."
if [ -d "./__pypackages__" ]; then
  echo "Prisma package directory exists:"
  ls -la ./__pypackages__
else
  echo "Creating Prisma package directory manually..."
  mkdir -p ./__pypackages__
  python -m prisma generate --schema=./prisma/schema.prisma
fi

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
if [ -d "./prisma" ]; then
  echo "Prisma directory exists:"
  ls -la ./prisma
fi

echo "Environment variables (masked):"
env | grep -v -E "SECRET|PASSWORD|KEY|DATABASE_URL" | sort

echo "Build completed successfully!" 