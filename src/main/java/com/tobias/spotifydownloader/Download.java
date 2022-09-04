package com.tobias.spotifydownloader;

import org.apache.tomcat.util.http.fileupload.FileUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.Resource;
import org.springframework.core.io.UrlResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.zeroturnaround.zip.ZipUtil;

import javax.servlet.http.HttpServletRequest;
import java.io.File;
import java.io.IOException;
import java.net.MalformedURLException;
import java.nio.file.Path;
import java.util.Random;

@CrossOrigin(origins = {"http://127.0.0.1:5500", "https://tobixnator.ddns.net", "https://other.ddns.net"})
@RestController
public class Download {
    @Autowired
    private FileStorageService fileStorageService;

    // get API for download
    @GetMapping(value = "/download")
    // get song and outputFormat
    public ResponseEntity<Resource> download(@RequestParam(value = "song", defaultValue = "") String song, @RequestParam(value = "outputFormat", defaultValue = "mp3") String outputFormat, @RequestParam(value = "lyrics", defaultValue = "musixmatch") String lyrics, HttpServletRequest request) {
        // increase downloads in Config
        try {
            Config.increaseDownloads();
        } catch (IOException e) {
            throw new RuntimeException(e);
        }

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
        File saveDirectory = new File(directory);
        saveDirectory.mkdirs();
        saveDirectory.setWritable(true);

        try {
            final Process p = Runtime.getRuntime().exec(Config.getStartCommand() + " spotdl --output " + directory +" --output-format " + outputFormat + " --lyrics-provider " + lyrics + " " + song);
            System.out.println(Config.getStartCommand() + " spotdl --output " + directory +" --output-format " + outputFormat + " --lyrics-provider " + lyrics + " \"" + song + "\"");

            /*
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
             */

            p.waitFor();
        } catch (IOException | InterruptedException e) {
            throw new RuntimeException(e);
        }
        ZipUtil.pack(saveDirectory, new File(Config.getSaveDirectory() + extendedPath + ".zip"));

        saveDirectory.delete();

        // Load file as Resource
        //Resource resource = fileStorageService.loadFileAsResource(Config.getSaveDirectory() + extendedPath + ".zip");
        Path filePath = Path.of(Config.getSaveDirectory() + extendedPath + ".zip");
        Resource resource = null;
        try {
            resource = new UrlResource(filePath.toUri());
        } catch (MalformedURLException e) {
            throw new RuntimeException(e);
        }


        // Try to determine file's content type
        String contentType = null;
        try {
            contentType = request.getServletContext().getMimeType(resource.getFile().getAbsolutePath());
        } catch (IOException ex) {
            ex.printStackTrace();
        }

        // Fallback to the default content type if type could not be determined
        if(contentType == null) {
            contentType = "application/octet-stream";
        }

        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(contentType))
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + resource.getFilename() + "\"")
                .body(resource);
    }

    // get API for download
    @GetMapping(value = "/downloadV2")
    // get song and outputFormat
    public String downloadV2(@RequestParam(value = "song", defaultValue = "") String song, @RequestParam(value = "outputFormat", defaultValue = "mp3") String outputFormat, @RequestParam(value = "lyrics", defaultValue = "musixmatch") String lyrics) {
        // increase downloads in Config
        try {
            Config.increaseDownloads();
        } catch (IOException e) {
            throw new RuntimeException(e);
        }

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
        File saveDirectory = new File(directory);
        saveDirectory.mkdirs();
        saveDirectory.setWritable(true);

        try {
            final Process p = Runtime.getRuntime().exec(Config.getStartCommand() + " spotdl --output " + directory +" --output-format " + outputFormat + " --lyrics-provider " + lyrics + " " + song);
            System.out.println(Config.getStartCommand() + " spotdl --output " + directory +" --output-format " + outputFormat + " --lyrics-provider " + lyrics + " \"" + song + "\"");

            /*
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
             */

            p.waitFor();
        } catch (IOException | InterruptedException e) {
            throw new RuntimeException(e);
        }
        ZipUtil.pack(saveDirectory, new File(Config.getSaveDirectory() + extendedPath + ".zip"));

        for(File file : saveDirectory.listFiles()){
            file.delete();
        }
        saveDirectory.delete();

        return extendedPath + ".zip";
    }

    @GetMapping(value = "/hello")
    public String sayHello(@RequestParam(value = "name", defaultValue = "World") String name) {
        return String.format("Hello %s!", name);
    }

    @GetMapping(value = "/downloads")
    public String returnDownloads(){
        return String.valueOf(Config.getDownloads());
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