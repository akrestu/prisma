FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# link previews (WhatsApp etc.) read only the first HTML: give it the PRISMA title, description and logo.
# PUBLIC_URL makes the preview image an absolute URL; override it with a build arg for another domain
ARG PUBLIC_URL=https://prisma.pt-wbk.id
RUN python deploy/brand_index.py "$PUBLIC_URL"
# run as an unprivileged user: a bug in the app must not give root inside the container
RUN useradd --system --uid 10001 --home-dir /app wanpis && chown -R wanpis /app
USER wanpis
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status != 200)"
# migrate first, then start the app
CMD ["sh", "-c", "alembic upgrade head && exec streamlit run app.py --server.port=8501 --server.address=0.0.0.0"]
