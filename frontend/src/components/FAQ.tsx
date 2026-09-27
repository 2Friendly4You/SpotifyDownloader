import { useTranslation, Trans } from "react-i18next";
import styles from "./FAQ.module.css";
import { useState } from "react";

function FAQ() {
  const { t } = useTranslation();
  const questions = t("FAQ.questions", { returnObjects: true }) as { q: string; a: string }[];
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const toggle = (idx: number) => {
    setOpenIndex(openIndex === idx ? null : idx);
  };

  return (
    <section className={styles.root}>
      <h1><Trans i18nKey="FAQ.title">FAQ</Trans></h1>
      <div className={styles.accordion}>
        {questions.map((item, idx) => (
          <div className={styles["faq-item"] + (openIndex === idx ? ` ${styles.open}` : "")} key={idx}>
            <button
              className={styles["faq-question"]}
              onClick={() => toggle(idx)}
              aria-expanded={openIndex === idx}
              aria-controls={`faq-panel-${idx}`}
              tabIndex={0}
            >
              <span>{item.q}</span>
              <span className={styles["faq-icon"]} aria-hidden="true">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M8.12 9.29L12 13.17L15.88 9.29C16.27 8.9 16.9 8.9 17.29 9.29C17.68 9.68 17.68 10.31 17.29 10.7L12.7 15.29C12.31 15.68 11.68 15.68 11.29 15.29L6.7 10.7C6.31 10.31 6.31 9.68 6.7 9.29C7.09 8.9 7.73 8.9 8.12 9.29Z" fill="currentColor"/>
                </svg>
              </span>
            </button>
            <div
              id={`faq-panel-${idx}`}
              className={styles["faq-answer"] + (openIndex === idx ? ` ${styles.open}` : "")}
              style={{ maxHeight: openIndex === idx ? 400 : 0 }}
            >
              <p>{item.a}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default FAQ;