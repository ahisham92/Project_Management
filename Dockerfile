# Optional: the app runs directly with "python run.py" and needs no container.
# This image is here for deploying it to a server.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY seed/ ./seed/
COPY run.py ./

# The database lives on a volume so it survives container replacement.
ENV DATA_DIR=/data
RUN mkdir -p /data
VOLUME ["/data"]

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/login').status==200 else 1)"

CMD ["python", "run.py"]
