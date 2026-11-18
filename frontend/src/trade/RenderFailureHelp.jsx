import { Link } from "react-router-dom"

export default function RenderFailureHelp({ hasUnsupportedRemarks = false, onEditTerms }) {
  return <>
    {hasUnsupportedRemarks ? <>
      <p>이번 PI의 원인은 거래 조건 → 비고에 입력된 한글입니다. 영문으로 바꾸거나 비고를 비운 뒤 다시 검토해 주세요.</p>
      {onEditTerms && <button className="btn" type="button" onClick={onEditTerms}>거래 조건의 비고 수정</button>}
    </> : <>
      <p>아래 설정과 문서 내용을 확인해 주세요.</p>
      <ul>
        <li><Link to="/settings?section=company">설정 → 회사 정보</Link>: 회사명(영문), 주소, 등록·발행 정보</li>
        <li><Link to="/settings?section=branding">설정 → 로고·직인</Link>: 직인 등록 여부와 PNG 형식(파일당 2MiB 이하)</li>
      </ul>
      <p>문서 입력값은 이 화면의 최종 검토에서 ‘수정’을 눌러 확인할 수 있습니다.</p>
    </>}
  </>
}