import requests

session = requests.Session()
try:
    # Test login
    response = session.post('http://127.0.0.1:5000/login', data={'username': 'admin', 'password': 'admin123'})
    print(f'Login status: {response.status_code}')
    print(f'Redirect location: {response.headers.get("Location", "None")}')
    print(f'Cookies after login: {list(session.cookies.keys())}')

    # Check response content
    if 'Invalid username or password' in response.text:
        print('❌ Invalid credentials message shown')
    elif 'Admin Dashboard' in response.text:
        print('✅ Login successful - admin dashboard in response')
    elif response.status_code == 302:
        print('✅ Redirect response received')
        # Follow the redirect
        redirect_response = session.get(response.headers['Location'])
        print(f'Redirect status: {redirect_response.status_code}')
        if 'Admin Dashboard' in redirect_response.text:
            print('✅ Admin dashboard accessible after redirect')
        else:
            print('❌ Redirect worked but dashboard not accessible')
    else:
        print('Response content preview:')
        print(response.text[:200] + '...' if len(response.text) > 200 else response.text)

except Exception as e:
    print(f'Error: {e}')