FROM python:3.12-slim


RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com bookworm main" > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update && apt-get install -y terraform

RUN curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh


RUN curl -fsSL https://get.pulumi.com | sh
ENV PATH="/root/.pulumi/bin:${PATH}"


WORKDIR /app


COPY . .

RUN pip install --no-cache-dir boto3 python-dotenv

ENTRYPOINT ["python", "script.py"]