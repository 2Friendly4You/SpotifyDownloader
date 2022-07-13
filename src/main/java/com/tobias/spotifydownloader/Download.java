package com.tobias.spotifydownloader;

import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.Random;

@CrossOrigin(origins = "http://127.0.0.1:5500")
@RestController
public class Download {

    // get API for download
    @GetMapping(value = "/download")
    // get song and outputFormat
    public Song download(@RequestParam(value = "song", defaultValue = "") String song, @RequestParam(value = "outputFormat", defaultValue = "mp3") String outputFormat) {
        // length of the directory name
        int directoryLength = Config.getDirectoryLength();
        String directory = Config.getSaveDirectory();
        String extendedPath = createDirectoryName(directoryLength);
        directory = directory + extendedPath;

        while(new File(directory).exists()){
            directory = Config.getSaveDirectory();
            extendedPath = createDirectoryName(directoryLength);
            directory = directory + extendedPath;

        }
        new File(directory).mkdirs();

        try {
            final Process p = Runtime.getRuntime().exec(Config.getStartCommand() + " spotdl --output " + directory +" --output-format " + outputFormat + " " + song);
            System.out.println(Config.getStartCommand() + " spotdl --output " + directory +" --output-format " + outputFormat + " \"" + song + "\"");

            new Thread(new Runnable() {
                public void run() {
                    BufferedReader input = new BufferedReader(new InputStreamReader(p.getInputStream()));
                    String line = null;

                    try {
                        while ((line = input.readLine()) != null)
                            System.out.println(line);
                    } catch (IOException e) {
                        e.printStackTrace();
                    }
                }
            }).start();

            p.waitFor();
        } catch (IOException | InterruptedException e) {
            throw new RuntimeException(e);
        }

        System.out.println();
        return new Song(song, outputFormat, directory);
    }

    @GetMapping(value = "/hello")
    public String sayHello(@RequestParam(value = "name", defaultValue = "World") String name) {
        return String.format("Hello %s!", name);
    }

    public static String createDirectoryName(int length){
        String lower = "abcdefghijklmnopqrstuvwxyz";
        String upper = lower.toUpperCase();
        String numbers = "1234567890";
        String all = lower + upper + numbers;

        Random random = new Random();
        StringBuilder builder = new StringBuilder();

        for (int i = 0; i < length; i++){
            char character = all.toCharArray()[random.nextInt(all.length())];
            builder.append(character);
        }
        return builder.toString();
    }
}