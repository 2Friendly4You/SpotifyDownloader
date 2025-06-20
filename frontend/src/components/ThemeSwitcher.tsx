import { useState, useEffect } from "react";
import styles from "./ThemeSwitcher.module.css";

function getInitialTheme() {
  const savedTheme = localStorage.getItem("theme");
  if (savedTheme) {
    return savedTheme;
  }

  const prefersDark =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}

function ThemeSwitcher() {
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  };

  return (
    <div className={styles.root}>
      <button onClick={toggleTheme} aria-label="Toggle theme">
        {theme === "light" ? (
          <span className="material-symbols-outlined" style={{ fontSize: 24, verticalAlign: "middle" }}>dark_mode</span>
        ) : (
          <span className="material-symbols-outlined" style={{ fontSize: 24, verticalAlign: "middle" }}>light_mode</span>
        )}
      </button>
    </div>
  );
}

export default ThemeSwitcher;
