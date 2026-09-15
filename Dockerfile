FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 user

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

EXPOSE 7860

CMD streamlit run src/wearable_insights/app.py \
    --server.port=${PORT:-7860} --server.address=0.0.0.0 --server.headless=true
