import http from 'k6/http';
import { check, sleep } from 'k6';

const apiUrl = (__ENV.DOCSURI_API_URL || 'https://d2bsni6xhpvbw1.cloudfront.net').replace(/\/$/, '');
const appUrl = (__ENV.DOCSURI_APP_URL || 'https://docsuri.org').replace(/\/$/, '');
const skipSearch = __ENV.DOCSURI_SKIP_SEARCH === '1';

export const options = {
  stages: [
    { duration: __ENV.DOCSURI_RAMP_UP || '30s', target: Number(__ENV.DOCSURI_VUS || 20) },
    { duration: __ENV.DOCSURI_HOLD || '2m', target: Number(__ENV.DOCSURI_VUS || 20) },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    'http_req_failed': ['rate<0.01'],
    'http_req_duration{target:frontend_home}': ['p(95)<1000'],
    'http_req_duration{target:api_ready}': ['p(95)<500'],
    'http_req_duration{target:api_search}': ['p(95)<3000'],
  },
};

export default function () {
  const responses = http.batch([
    ['GET', `${appUrl}/`, null, { tags: { target: 'frontend_home' } }],
    ['GET', `${apiUrl}/readyz`, null, { tags: { target: 'api_ready' } }],
  ]);

  check(responses[0], {
    'frontend home 200': (response) => response.status === 200,
  });
  check(responses[1], {
    'api ready 200': (response) => response.status === 200,
  });

  if (!skipSearch && Math.random() < 0.2) {
    const search = http.post(
      `${apiUrl}/api/search`,
      JSON.stringify({ query: 'transformer attention retrieval' }),
      {
        headers: { 'Content-Type': 'application/json' },
        tags: { target: 'api_search' },
      },
    );
    check(search, {
      'api search not 5xx': (response) => response.status < 500,
    });
  }

  sleep(1);
}
