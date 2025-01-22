# SpotifyDownloader
A simple webui for downloading Spotify songs and playlists using spotdl. 
You can choose the format, the audio provider and the lyrics provider for the songs.

## Features
- Download songs and playlists from Spotify
- Choose the format of the audio file
- Choose the audio provider
- Choose the lyrics provider

## Get started
1. Start the docker container
```bash
docker-compose up --build
```
2. Delete the docker container
```bash
docker-compose down
```

3. Stop docker container with deleting the volume
```bash
docker-compose down -v
```

## Change the exposed port
If you want to change the exposed port, you have to change the port in the `docker-compose.yml` file. 
```yaml
  spotifydownloader-nginx:
    ports:
      - "8900:80"
```
You have to change the `8900` to your desired port.