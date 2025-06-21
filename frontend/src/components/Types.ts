type Request = {
  id: number;
  title: string;
  description: string;
  createdAt: string;
};

enum RequestStatus {
  PENDING = "pending",
  DOWNLOADED = "downloaded",
  FAILED = "failed",
}

export type { Request };
export { RequestStatus };