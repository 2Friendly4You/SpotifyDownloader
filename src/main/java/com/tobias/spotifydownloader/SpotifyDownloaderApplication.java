package com.tobias.spotifydownloader;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.IOException;

@SpringBootApplication
@EnableConfigurationProperties({
		FileStorageProperties.class
})
@EnableWebMvc
@Configuration
public class SpotifyDownloaderApplication {

	public static void main(String[] args) {
		// create config
		try {
			Config.loadConfig();
		} catch (IOException e) {
			throw new RuntimeException(e);
		}

		// start server
		SpringApplication.run(SpotifyDownloaderApplication.class, args);
	}

	/*
	@Bean
	public WebMvcConfigurer corsConfigurer(){
		return new WebMvcConfigurer() {
			@Override
			public void addCorsMappings(CorsRegistry registry) {
				registry.addMapping("/hello").allowedOrigins("http://127.0.0.1:5500");
			}
		};
	}
	 */
}
