# mail
Apps related to Odoo it's e-mail features:
- [mail_parser](#mail_parser): allow parsing incoming emails from an email alias to get content out and doing operations on the data.


## mail_parser
This app adds support to parse content from an email that is coming into Odoo through an alias.
Through this app you can configure regex rules on aliasses to parse values out of an email and create new records in Odoo.
A sample configuration of an alias (Settings > Technical > Email > Aliases:
<img width="995" alt="image" src="https://github.com/Yenthe666/mail/assets/6352350/059bf670-7c32-47cd-a453-2dbad86044d0">

In this case when an email is sent to tasks@yourdomain.com this app will parse the whole email body with the "mail parser rules" (regex).
On every rule you can configure a few things:
- "Name": just so you know what this rule is about (informative)
- "Regex condition": a Python regex you can add (tip: you can test with https://pythex.org/)
- "Model": on which model a new record should be created when the parsing of the email was finished
- "Field": to which field we should map the result of the parsed (regex) content
- "Default value": a fallback value that will be set if the regex itself gives nothing back (so it is a fallback)
- "Should be Unique": If this field is toggled on we will do a search on the configured model to see if we find any matching record matching.
In this example we will find the email in an email and will then check if we find any existing contact (res.partner) in Odoo. If we find one we will not create a new record, if we do not find an existing contact we create a new one.
If multiple rules are configured with "Should be unique" we will do a search on all of them with an AND condition, not an OR condition.

Under the tab "Test Mail Body" you can paste a text representing the content of an email you wish to test.
This can be used to quick check/test the rules and conditions through the button "Test Parser". A sample after clicking on it:
<img width="739" alt="image" src="https://github.com/Yenthe666/mail/assets/6352350/d5027813-c07e-4933-a2f4-73365ce91a24">

Under the alias itself there is also a new field named "Mail parser server action".
In the example screenshot you can see we set a action "Link contact to task".
This is done to execute code after the alias its email has been parsed. 
A sample here could be that you wish to automatically create a new contact from an alias that already generates a task and that you then want to link the contact to the task too:
<img width="1263" alt="image" src="https://github.com/Yenthe666/mail/assets/6352350/f86d6404-d0a0-4604-b120-b6e7a13bed3e">

This could also be used to trigger other actions, send an SMS, create activities and many more options.
