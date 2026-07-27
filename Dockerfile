FROM python:3.13-slim

# Install system dependencies required for Manim, FFmpeg, Cairo, Pango, and LaTeX
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libcairo2-dev \
    libpango1.0-dev \
    texlive \
    texlive-latex-extra \
    texlive-fonts-extra \
    texlive-latex-recommended \
    texlive-science \
    texlive-fonts-extra \
    tipa \
    pkg-config \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Django project code
COPY . .

# Expose port for Render
EXPOSE 10000

# Start Gunicorn server
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:10000", "--workers", "2", "--timeout", "120"]
