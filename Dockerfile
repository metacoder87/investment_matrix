FROM python:3.12-slim

WORKDIR /code

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10

# Copy requirements and install dependencies
COPY ./requirements.txt /code/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --prefer-binary --no-cache-dir -r /code/requirements.txt

# Copy the application code
COPY . /code/

# Command to run the uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
