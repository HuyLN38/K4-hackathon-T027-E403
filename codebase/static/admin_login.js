/* Đăng nhập Labcoach. */

const go = $('#go');
const msg = $('#msg');

async function login() {
  go.disabled = true;
  setAlert(msg, '');
  try {
    await api('/api/admin/login', {
      method: 'POST',
      body: { username: $('#u').value.trim(), password: $('#p').value },
    });
    location.href = '/admin';
  } catch (err) {
    setAlert(msg, err.message);
    go.disabled = false;
  }
}

go.addEventListener('click', login);
$('#p').addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });
$('#u').focus();
