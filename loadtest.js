import http from 'k6/http';
import { sleep } from 'k6';

const vus = Number(__ENV.VUS || 500);
const duration = __ENV.DURATION || '10m';
const rampUp = __ENV.RAMP_UP || '5s';
const thinkTime = Number(__ENV.THINK_TIME || 0);
const target = __ENV.TARGET || 'https://example.com/';
const userAgent = __ENV.USER_AGENT || 'loadtest-codespace/1.0';

export const options = {
  stages: [
    { duration: rampUp === '0s' ? '1s' : rampUp, target: vus },
    { duration: duration, target: vus },
  ],
  discardResponseBodies: true,
  userAgent: userAgent,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  thresholds: {
    http_req_failed: ['rate<0.25'],
  },
};

export default function () {
  http.get(target, { tags: { name: 'target' } });
  if (thinkTime > 0) {
    sleep(thinkTime);
  }
}
