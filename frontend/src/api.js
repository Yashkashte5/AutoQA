import axios from "axios";

const api = axios.create({ baseURL: "http://127.0.0.1:8000" });

export const createSuite = (formData) => api.post("/suites/", formData);
export const triggerRun = (suiteId) => api.post(`/runs/${suiteId}`);
export const getRun = (runId) => api.get(`/runs/${runId}`);
export const getRunResults = (runId) => api.get(`/runs/${runId}/results`);