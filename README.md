# BatteryPV Federated Digital Twin

## Prerequisites

- Docker
- `repoUrls.env` filled out with AWS credentials and GitHub credentials

## Build

```bash
docker build -t batterypv-example .
```

## Usage

Start a persistent container to avoid re-cloning repos and re-installing dependencies on every run:

```bash
docker run -it -d -v /var/run/docker.sock:/var/run/docker.sock -v batterypv-data:/app --name batterypv -p 5000:5000 --entrypoint sleep batterypv-example infinity
```

Then use `docker exec` for all commands:

### Deploy Twins
```bash
docker exec batterypv python script.py deploy:twins
```

### Deploy Simulator
```bash
docker exec batterypv python script.py deploy:simulator
```

### Deploy FedTwin
```bash
docker exec batterypv python script.py deploy:fedtwin
```

### Destroy All
```bash
docker exec batterypv python script.py destroy
```

### Destroy Twins
```bash
docker exec batterypv python script.py destroy:twins
```

### Destroy Simulator
```bash
docker exec batterypv python script.py destroy:simulator
```

### Destroy FedTwin
```bash
docker exec batterypv python script.py destroy:fedtwin
```

## Cleanup

```bash
docker rm -f batterypv
docker volume rm batterypv-data
```

# Bash
```bash
docker exec -it batterypv /bin/bash
```