package com.tobias.spotifydownloader;

import com.sun.security.auth.login.ConfigFile;

import java.io.*;
import java.util.Properties;

public class Config {
    static File configFile = new File("config.properties");
    private static String saveDirectory = "C:\\Users\\schueler\\Desktop\\Musik\\";
    private static int directoryLength = 20;
    private static String startCommand = "cmd.exe /c";
    private static int downloads = 0;

    public static void loadConfig() throws IOException {
        FileInputStream propsInput = null;
        Properties prop = null;

        if (configFile.exists()){
            propsInput = new FileInputStream(configFile);
            prop = new Properties();
            prop.load(propsInput);

            saveDirectory = prop.getProperty("saveDirectory");
            directoryLength = Integer.parseInt(prop.getProperty("directoryLength"));
            startCommand = prop.getProperty("startCommand");
            downloads = Integer.parseInt(prop.getProperty("downloads"));
        } else {
            configFile.createNewFile();

            Properties props = new Properties();
            props.setProperty("saveDirectory", saveDirectory);
            props.setProperty("directoryLength", String.valueOf(directoryLength));
            props.setProperty("startCommand", startCommand);
            props.setProperty("downloads", String.valueOf(downloads));
            FileWriter writer = new FileWriter(configFile);
            props.store(writer, "host settings");
            writer.close();
        }
    }

    public static String getSaveDirectory() {
        return saveDirectory;
    }

    public static int getDirectoryLength() {
        return directoryLength;
    }

    public static String getStartCommand(){
        return startCommand;
    }

    public static int getDownloads(){
        return downloads;
    }

    public static void setDownloads(int downloads) throws IOException {
        FileInputStream propsInput = null;
        Properties props = null;

        Config.downloads = downloads;

        propsInput = new FileInputStream(configFile);
        props = new Properties();
        props.load(propsInput);

        props.setProperty("downloads", String.valueOf(downloads));
        FileWriter writer = new FileWriter(configFile);
        props.store(writer, "host settings");
        writer.close();
    }

    public static void increaseDownloads() throws IOException {
        FileInputStream propsInput = null;
        Properties props = null;

        Config.downloads = Config.downloads + 1;

        propsInput = new FileInputStream(configFile);
        props = new Properties();
        props.load(propsInput);

        props.setProperty("downloads", String.valueOf(downloads));
        FileWriter writer = new FileWriter(configFile);
        props.store(writer, "host settings");
        writer.close();
    }
}
