import { useTranslation } from "react-i18next";
import styles from "./LanguageSwitcher.module.css";

function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const language = (i18n.resolvedLanguage || i18n.language || "en").split("-")[0];

  return (
    <select className={styles.root}
      value={language === "de" ? "de" : "en"}
      onChange={(e) => i18n.changeLanguage(e.target.value)}
    >
      <option value="en">🇬🇧 English</option>
      <option value="de">🇩🇪 Deutsch</option>
    </select>
  );
}

export default LanguageSwitcher;
