import { Trans } from "react-i18next";
import styles from "./AdminPage.module.css";

function AdminPage() {
  return (
    <div className={styles.root}>
      <h1><Trans i18nKey="AdminPage.adminPage">Admin Page</Trans></h1>
      <p><Trans i18nKey="AdminPage.adminPageDescription">This is the admin page. Add admin features here.</Trans></p>
    </div>
  );
}

export default AdminPage; 