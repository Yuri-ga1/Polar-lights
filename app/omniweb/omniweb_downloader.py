from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from requests import Response


@dataclass(frozen=True)
class OmniWebConfig:
    base_url: str = "https://omniweb.gsfc.nasa.gov"
    form_path: str = "/form/omni_min.html"
    timeout: int = 30
    variables: dict[str, str] = field(
        default_factory=lambda: {
            "SYM-H": "SYM_H",
            "AE": "AE_INDEX",
            "Flow Speed": "FLOW_SPEED",
            "IMF Bz (GSM)": "BZ_GSM",
            "IMF By (GSM)": "BY_GSM",
            "IMF Magnitude": "IMF_MAG",
        }
    )
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


class OmniWebDownloader:
    def __init__(self, config: OmniWebConfig | None = None) -> None:
        self.config = config or OmniWebConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.config.user_agent})

    def download_day(
        self,
        day: date,
        output_dir: Path | str,
        variables: Iterable[str] | None = None,
        file_pattern: str | None = None,
    ) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        form_html = self._get_form_html()
        form_action, form_payload, variable_options = self._parse_form(form_html)
        payload = self._build_payload(
            base_payload=form_payload,
            day=day,
            variables=variables,
            variable_options=variable_options,
        )

        response = self.session.post(
            form_action, data=payload, timeout=self.config.timeout
        )
        response.raise_for_status()

        if self._looks_like_data(response):
            return self._save_response(response, output_dir)

        download_response = self._follow_file_selection(
            response.text, file_pattern=file_pattern
        )
        return self._save_response(download_response, output_dir)

    def _get_form_html(self) -> str:
        url = f"{self.config.base_url}{self.config.form_path}"
        response = self.session.get(url, timeout=self.config.timeout)
        response.raise_for_status()
        return response.text

    def _parse_form(self, html: str) -> tuple[str, dict[str, str], dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form")
        if not form or not form.get("action"):
            raise ValueError("Unable to locate OmniWeb form action.")

        action = form["action"]
        if action.startswith("/"):
            action = f"{self.config.base_url}{action}"
        elif not action.startswith("http"):
            action = f"{self.config.base_url}/{action}"

        payload: dict[str, str] = {}
        for input_tag in form.find_all("input"):
            name = input_tag.get("name")
            if not name:
                continue
            input_type = (input_tag.get("type") or "").lower()
            if input_type == "submit":
                continue
            if input_tag.get("value") is not None:
                payload[name] = input_tag.get("value", "")

        variable_options: dict[str, str] = {}
        for select in form.find_all("select"):
            name = select.get("name")
            if name and name not in payload:
                payload[name] = ""
            for option in select.find_all("option"):
                label = option.text.strip()
                value = option.get("value", "").strip()
                if label and value:
                    variable_options[label] = value

        return action, payload, variable_options

    def _build_payload(
        self,
        base_payload: dict[str, str],
        day: date,
        variables: Iterable[str] | None,
        variable_options: dict[str, str],
    ) -> dict[str, str]:
        payload = dict(base_payload)

        self._apply_date_fields(payload, day)
        self._apply_variable_fields(payload, variables, variable_options)
        self._ensure_activity(payload)

        return payload

    def _apply_date_fields(self, payload: dict[str, str], day: date) -> None:
        year, month, day_num = day.year, day.month, day.day
        date_formats = {
            "start_date": day.strftime("%Y-%m-%d"),
            "end_date": day.strftime("%Y-%m-%d"),
            "start": day.strftime("%Y-%m-%d"),
            "end": day.strftime("%Y-%m-%d"),
        }
        for key, value in date_formats.items():
            if key in payload:
                payload[key] = value

        numeric_fields = {
            "year": year,
            "month": month,
            "day": day_num,
            "start_year": year,
            "start_month": month,
            "start_day": day_num,
            "end_year": year,
            "end_month": month,
            "end_day": day_num,
        }
        for key, value in numeric_fields.items():
            if key in payload:
                payload[key] = str(value)

        time_fields = {
            "start_hour": "0",
            "start_minute": "0",
            "end_hour": "23",
            "end_minute": "59",
            "start_min": "0",
            "end_min": "59",
        }
        for key, value in time_fields.items():
            if key in payload:
                payload[key] = value

    def _apply_variable_fields(
        self,
        payload: dict[str, str],
        variables: Iterable[str] | None,
        variable_options: dict[str, str],
    ) -> None:
        desired = list(variables) if variables else list(self.config.variables.keys())
        resolved_values: list[str] = []
        for label in desired:
            if label in variable_options:
                resolved_values.append(variable_options[label])
                continue
            if label in self.config.variables:
                resolved_values.append(self.config.variables[label])

        if not resolved_values:
            return

        for key in ("vars", "var", "variables", "parameters"):
            if key in payload:
                payload[key] = ",".join(resolved_values)
                break

    def _ensure_activity(self, payload: dict[str, str]) -> None:
        if "activity" in payload and not payload["activity"]:
            payload["activity"] = "retrieve"

    def _looks_like_data(self, response: Response) -> bool:
        content_type = response.headers.get("content-type", "")
        if "text/plain" in content_type or "application/octet-stream" in content_type:
            return True
        text = response.text.lstrip()
        return text.startswith(":") or text.startswith("YEAR") or text.startswith("#")

    def _follow_file_selection(
        self, html: str, file_pattern: str | None = None
    ) -> Response:
        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a"):
            href = link.get("href")
            if not href:
                continue
            if href.endswith((".txt", ".dat", ".cdf", ".asc")):
                return self._get_url(href)

        form = soup.find("form")
        if not form or not form.get("action"):
            raise ValueError("Unable to locate file selection form.")

        action = form["action"]
        if action.startswith("/"):
            action = f"{self.config.base_url}{action}"
        elif not action.startswith("http"):
            action = f"{self.config.base_url}/{action}"

        payload: dict[str, str] = {}
        select_name = None
        options: list[str] = []

        for input_tag in form.find_all("input"):
            name = input_tag.get("name")
            if not name:
                continue
            input_type = (input_tag.get("type") or "").lower()
            if input_type == "submit":
                continue
            if input_tag.get("value") is not None:
                payload[name] = input_tag.get("value", "")

        for select in form.find_all("select"):
            select_name = select.get("name")
            if not select_name:
                continue
            for option in select.find_all("option"):
                value = option.get("value", "").strip()
                if value:
                    options.append(value)

        if not select_name or not options:
            raise ValueError("No file options found on OmniWeb file selection page.")

        chosen = self._choose_file_option(options, file_pattern)
        payload[select_name] = chosen

        response = self.session.post(action, data=payload, timeout=self.config.timeout)
        response.raise_for_status()
        return response

    def _choose_file_option(self, options: list[str], file_pattern: str | None) -> str:
        if file_pattern:
            for option in options:
                if file_pattern in option:
                    return option
        return options[0]

    def _get_url(self, href: str) -> Response:
        url = href
        if href.startswith("/"):
            url = f"{self.config.base_url}{href}"
        elif not href.startswith("http"):
            url = f"{self.config.base_url}/{href}"
        response = self.session.get(url, timeout=self.config.timeout)
        response.raise_for_status()
        return response

    def _save_response(self, response: Response, output_dir: Path) -> Path:
        filename = self._infer_filename(response)
        filepath = output_dir / filename
        filepath.write_bytes(response.content)
        return filepath

    def _infer_filename(self, response: Response) -> str:
        content_disposition = response.headers.get("content-disposition", "")
        if "filename=" in content_disposition:
            return content_disposition.split("filename=")[-1].strip('"')
        return "omniweb_data.txt"
