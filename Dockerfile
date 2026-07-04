# 1. Use the official lightweight Python image
FROM python:3.13-slim

# 2. Install system-level dependencies (compilers needed for math/vector libraries)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Copy requirements and install Python libraries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the project source code
COPY . .

# 6. Expose the API port (8000)
EXPOSE 8000

# 7. Start the FastAPI server using Uvicorn
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
