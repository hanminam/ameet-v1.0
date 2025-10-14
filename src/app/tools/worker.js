// src/app/tools/worker.js

let isPollingActive = false;
let discussionId;
let token;
const POLLING_INTERVAL_MS = 3000;
let retryCount = 0; // 재시도 횟수 카운터
const MAX_RETRIES = 5; // 최대 재시도 횟수

/**
 * 서버에 토론 상태를 GET으로 요청하고, 완료되면 다음 요청을 스케줄링하는 함수 (재시도 로직 추가)
 */
async function pollDiscussionStatus() {
    // isPollingActive 플래그를 먼저 확인하여, 중지 명령을 받았으면 즉시 중단
    if (!isPollingActive) {
        self.postMessage({ type: 'status', status: 'stopped' });
        return;
    }

    try {
        const response = await fetch(`/api/v1/discussions/${discussionId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            retryCount = 0; // 성공 시 재시도 카운터 초기화
            const discussionData = await response.json();
            // 메인 스레드로 데이터 전송
            self.postMessage({ type: 'data', data: discussionData });

            // 특정 상태가 되면 폴링 중지
            if (discussionData.status === 'waiting_for_vote' || discussionData.status === 'completed' || discussionData.status === 'failed') {
                isPollingActive = false; // 루프 중단 플래그 설정
            }
        } else {
            retryCount++;
            self.postMessage({ type: 'error', error: `Polling failed with status: ${response.status}. Retry ${retryCount}/${MAX_RETRIES}...` });
            if (retryCount >= MAX_RETRIES) {
                isPollingActive = false; // 루프 중단
            }
        }
    } catch (error) {
        retryCount++;
        self.postMessage({ type: 'error', error: `Polling network error: ${error.message}. Retry ${retryCount}/${MAX_RETRIES}...` });
        if (retryCount >= MAX_RETRIES) {
            isPollingActive = false; // 루프 중단
        }
    } finally {
        // 여전히 폴링이 활성 상태이면, 다음 인터벌 후에 다시 함수를 호출
        if (isPollingActive) {
            setTimeout(pollDiscussionStatus, POLLING_INTERVAL_MS);
        } else {
            self.postMessage({ type: 'status', status: 'stopped' });
        }
    }
}

self.onmessage = function(e) {
    const { command, data } = e.data;

    if (command === 'start') {
        discussionId = data.discussionId;
        token = data.token;
        if (!isPollingActive) {
            isPollingActive = true;
            self.postMessage({ type: 'status', status: 'started' });
            pollDiscussionStatus(); // 재귀 루프 시작
        }
    } else if (command === 'stop') {
        isPollingActive = false; // 루프가 다음 반복에서 멈추도록 플래그 설정
    }
};
