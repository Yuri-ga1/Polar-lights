class BackendError(Exception):
    def __init__(self, code, message, status=400, **details):
        super().__init__(message)
        self.code, self.message, self.status, self.details = (
            code,
            message,
            status,
            details,
        )

    def body(self):
        return {"code": self.code, "message": self.message, "details": self.details}
