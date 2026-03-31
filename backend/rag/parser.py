import json, yaml

def parse_openapi_spec(raw: str) -> list[dict]:
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        spec = yaml.safe_load(raw)

    endpoints = []
    components = spec.get("components", {})

    for path, methods in spec.get("paths", {}).items():
        for method, details in methods.items():
            if method not in ["get", "post", "put", "patch", "delete"]:
                continue

            # extract all defined response codes from spec
            raw_responses = details.get("responses", {})
            expected_responses = []
            for code in raw_responses.keys():
                try:
                    expected_responses.append(int(code))
                except (ValueError, TypeError):
                    pass  # skip "default" etc

            # extract required params and their types
            parameters = details.get("parameters", [])
            required_params = [
                p["name"] for p in parameters
                if p.get("required", False)
            ]
            enum_values = {}
            for p in parameters:
                schema = p.get("schema", {})
                if "enum" in schema:
                    enum_values[p["name"]] = schema["enum"]

            endpoints.append({
                "path": path,
                "method": method.upper(),
                "summary": details.get("summary", ""),
                "parameters": parameters,
                "required_params": required_params,
                "enum_values": enum_values,
                "request_body": details.get("requestBody", {}),
                "responses": raw_responses,
                "expected_responses": expected_responses,
                "security": details.get("security", spec.get("security", [])),
                "components": components,
            })
    return endpoints