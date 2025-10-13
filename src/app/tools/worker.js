// src/app/tools/worker.js

let pollingInterval;
let isPollingActive = false;
let discussionId;
let token;

/**
 * 서버에 토론 상태를 GET으로 요청하는 함수
 */
async function pollDiscussionStatus() {
    if (!isPollingActive || !discussionId || !token) {
        return;
    }

    try {
        const response = await fetch(`/api/v1/discussions/${discussionId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            const discussionData = await response.json();
            // 메인 스레드로 데이터 전송
            self.postMessage({ type: 'data', data: discussionData });

            // 특정 상태가 되면 폴링 중지
            if (discussionData.status === 'waiting_for_vote' || discussionData.status === 'completed' || discussionData.status === 'failed') {
                self.postMessage({ type: 'status', status: 'stopped' });
                isPollingActive = false;
                clearInterval(pollingInterval);
            }
        } else {
            self.postMessage({ type: 'error', error: `Polling failed with status: ${response.status}` });
            isPollingActive = false;
            clearInterval(pollingInterval);
        }
    } catch (error) {
        self.postMessage({ type: 'error', error: `Polling network error: ${error.message}` });
        isPollingActive = false;
        clearInterval(pollingInterval);
    }
}

self.onmessage = function(e) {
    const { command, data } = e.data;

    if (command === 'start') {
        discussionId = data.discussionId;
        token = data.token;
        if (!isPollingActive) {
            isPollingActive = true;
            // 즉시 첫 실행 후 3초 간격으로 반복
            pollDiscussionStatus();
            pollingInterval = setInterval(pollDiscussionStatus, 3000);
            self.postMessage({ type: 'status', status: 'started' });
        }
    } else if (command === 'stop') {
        isPollingActive = false;
        clearInterval(pollingInterval);
        self.postMessage({ type: 'status', status: 'stopped' });
    }
};