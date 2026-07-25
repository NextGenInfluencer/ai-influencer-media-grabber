FROM python:3.10-slim

# Create a non-root user 'user' (required for Hugging Face Spaces)
RUN useradd -m -u 1000 user

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Switch to non-root user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Copy requirements file and install dependencies
COPY --chown=user requirements_web.txt .
RUN pip install --no-cache-dir -r requirements_web.txt

# Copy application source code
COPY --chown=user . .

# Expose port (Gradio default is 7860)
EXPOSE 7860

# Run the web application
CMD ["python", "app_web.py"]
