# ChemAgentSys Docker Deployment

This guide explains how to run the prebuilt ChemAgentSys website on a Linux server using Docker.

## Requirements

- A Linux server with Docker Engine installed and running.
- Access to Docker commands, either as a user with Docker permissions or with `sudo`.
- An `x86_64` server. The supplied image targets `linux/amd64`.
- An SSH connection to the server and a browser on your computer.

## 1. Download the image

Download `chem-agent-website.tar.gz` from GoogleDrive:

**Download link:** [GoogleDrive](https://drive.google.com/file/d/1LBFoSS0Gli-Ag3MmbMVsTuS0E8XBTmgw/view?usp=sharing)

Transfer the downloaded file to the server, for example:

```bash
scp chem-agent-website.tar.gz USER@SERVER:~/
```

Replace `USER@SERVER` with your SSH username and server address. The remaining commands run on the server after you connect with SSH. If your account requires `sudo` to access Docker, prefix each `docker` command below with `sudo`.

## 2. Load and start the image

Run these commands in the directory containing the image archive:

```bash
docker load -i chem-agent-website.tar.gz

docker run -d \
  --name chem-agent-website \
  --restart unless-stopped \
  -p 127.0.0.1:9000:9000 \
  chem-agent-website:latest
```

The website listens on the server's loopback interface, so it is not exposed directly to the network. If port `9000` is already in use on the server, change the first `9000` in the port mapping to an available port, for example `127.0.0.1:9001:9000`. Use that server port in the SSH tunnel command below.

Check that the container is running:

```bash
docker ps --filter name=chem-agent-website
curl -f http://127.0.0.1:9000/
```

The second command should return HTML. If you chose a different server port, substitute it for `9000`.

## 3. Open the website

On your own computer, open a **separate terminal** and create an SSH tunnel:

```bash
ssh -N -L 9000:127.0.0.1:9000 USER@SERVER
```

Keep that terminal open, then visit [http://localhost:9000](http://localhost:9000) in your browser. Press `Ctrl+C` in the tunnel terminal when you are finished.

In the tunnel command, the first `9000` is the port on your computer and the last `9000` is the server port. If either port is already in use, adjust it accordingly. For example, if the server port is `9001` and your computer's port `9000` is unavailable, use `ssh -N -L 19000:127.0.0.1:9001 USER@SERVER`, then visit `http://localhost:19000`.

## Manage the container

```bash
# Show logs
docker logs --tail 100 chem-agent-website

# Stop the website
docker stop chem-agent-website

# Start it again
docker start chem-agent-website
```

## What is included

The image runs the website and its API and includes the task history and agent configuration present when it was built. It does not start the Python worker or supply model services, databases, or laboratory devices, so features that depend on those services may not work.
