import SettingsForm, { Field } from "./SettingsForm"

export default function CompanySettings({ data, save, ...status }) {
  const company = data.company ?? {}
  return (
    <SettingsForm {...status} onSubmit={(values) => save("/company", values)}>
      <Field label="회사명 (영문)" name="legal_name_en" value={company.legal_name_en} />
      <Field label="회사명 (국문)" name="company_name" value={company.company_name} />
      <Field label="사업자등록번호" name="business_no" value={company.business_no} />
      <Field label="대표자" name="ceo_name" value={company.ceo_name} />
      <Field label="이메일" name="email" type="email" value={company.email} />
      <Field label="전화번호" name="phone" type="tel" value={company.phone} />
      <Field label="담당자·연락처" name="contact" value={company.contact} />
      <Field label="주소" name="address" value={company.address} multiline rows={2} />
      <Field label="등록·발행 정보" name="registration_details" value={company.registration_details} multiline rows={2} />
    </SettingsForm>
  )
}
