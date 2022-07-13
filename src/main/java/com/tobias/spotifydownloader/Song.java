package com.tobias.spotifydownloader;

public class Song {
    private final String song;
    private final String outputFormat;
    private String directory = null;


    public Song(String song, String outputFormat, String directory) {
        this.song = song;
        this.outputFormat = outputFormat;
        this.directory = directory;
    }

    public String getSong() {
        return song;
    }

    public String getOutputFormat() {
        return outputFormat;
    }

    public String getDirectory() {
        return directory;
    }

    public void setDirectory(String directory) {
        this.directory = directory;
    }
}
