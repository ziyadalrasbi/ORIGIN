# Contributing to ORIGIN

Thank you for your interest in contributing to ORIGIN!

## Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ORIGIN.git
   cd ORIGIN
   ```

3. Set up environment:
   ```bash
   copy env.example .env  # Windows
   # or
   cp env.example .env    # Linux/Mac
   ```

4. Start services:
   ```bash
   docker-compose up -d
   ```

5. Run migrations:
   ```bash
   docker-compose exec api alembic upgrade head
   ```

6. Seed data:
   ```bash
   docker-compose exec api python -m origin_api.cli seed
   ```

## Development Workflow

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes

3. Run tests:
   ```bash
   docker-compose exec api pytest tests/ -v
   ```

4. Commit your changes:
   ```bash
   git add .
   git commit -m "Description of your changes"
   ```

5. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

6. Create a Pull Request on GitHub

## Code Style

- Follow PEP 8 for Python code
- Use type hints where possible
- Add docstrings to functions and classes
- Run linters before committing

## Testing

- Write tests for new features
- Ensure all tests pass before submitting PR
- Aim for >80% code coverage

## Documentation

- Update README.md if adding new features
- Add docstrings to new functions/classes
- Update API documentation if endpoints change

