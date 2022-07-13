package com.tobias.spotifydownloader;

import java.io.*;
import java.util.Properties;

public class Config {
    static File configFile = new File("config.properties");
    private static String saveDirectory = "C:\\Users\\schueler\\Desktop\\Musik\\";
    private static int directoryLength = 20;
    private static String startCommand = "cmd.exe /c";

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
        } else {
            configFile.createNewFile();

            Properties props = new Properties();
            props.setProperty("saveDirectory", saveDirectory);
            props.setProperty("directoryLength", String.valueOf(directoryLength));
            props.setProperty("startCommand", startCommand);
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
}
