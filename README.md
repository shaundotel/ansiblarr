# Ansible arr Provisioning

This repo contains Ansible configuration to setup *arr services.

This is under development.

# Features

1. gluetun
1. nginx
1. overseerr
1. plex_server
1. prowlarr
1. qbittorrent
1. radarr
1. sonarr
1. tautulli

The setup uses `docker compose`.

# Requirements

## Controller
1. ansible

## Host
1. docker
1. docker-compose

# Run

```
export ARR_HOST=<host_name>
ansible-playbook site.yml
```