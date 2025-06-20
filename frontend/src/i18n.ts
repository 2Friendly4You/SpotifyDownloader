import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';

import enTranslations from './locales/en/translations.json';
import deTranslations from './locales/de/translations.json';

const resources = {
    en: {
        translation: enTranslations
    },
    de: {
        translation: deTranslations
    }
}

// Configure language detector options to persist language in localStorage and not override manual changes
const detectionOptions = {
  // order and from where user language should be detected
  order: ['localStorage', 'navigator', 'htmlTag'],
  // keys or params to lookup language from
  lookupLocalStorage: 'i18nextLng',
  // cache user language on
  caches: ['localStorage'],
  // do not set cookie
  cookieMinutes: 0,
  // do not use querystring or sessionStorage (by not including them in order)
};

i18n
  // detect user language
  // learn more: https://github.com/i18next/i18next-browser-languageDetector
  .use(LanguageDetector)
  // pass the i18n instance to react-i18next.
  .use(initReactI18next)
  // init i18next
  // for all options read: https://www.i18next.com/overview/configuration-options
  .init({
    resources,
    fallbackLng: 'en',
    debug: true,
    detection: detectionOptions,
    interpolation: {
      escapeValue: false,
    },
    react: {
      useSuspense: false,
      transSupportBasicHtmlNodes: true,
      transKeepBasicHtmlNodesFor: ['br', 'strong', 'i', 'p']
    }
  });

export default i18n;