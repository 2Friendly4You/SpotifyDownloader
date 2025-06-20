import styles from "./SearchFields.module.css";
import { Trans, useTranslation } from "react-i18next";

function SearchFields() {
    const { t } = useTranslation();

    return (
        <div className={styles.root}>
            <input type="text" placeholder={t("SearchFields.search")} />
            <button><Trans i18nKey="SearchFields.search">Search</Trans></button>
        </div>
    )
}

export default SearchFields;